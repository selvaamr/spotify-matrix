"""
@file settings.py
@brief Persistencia de los ajustes del usuario en un archivo JSON (settings.json).

Guarda qué escena estaba activa, el brillo y los ajustes de cada escena, para que
la matriz recuerde la configuración al reiniciarse. El archivo es tolerante a
errores: si no existe o está corrupto se usan los valores por defecto.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

## Segundos que se espera antes de escribir en disco, para agrupar cambios seguidos (p. ej. al arrastrar un deslizador).
SAVE_DELAY_SECONDS = 1.0


class SettingsStore:
    """
    @brief Almacén de ajustes con guardado diferido y atómico.

    Es seguro usarlo desde varios hilos (el servidor web y el programa principal).
    """

    def __init__(self, path: Path = Path("settings.json")) -> None:
        """
        @brief Crea el almacén y carga el archivo si existe.
        @param path Ruta del archivo JSON.
        """
        ## Ruta del archivo JSON.
        self.path = path
        ## Cerrojo que protege los datos y el temporizador.
        self._lock = threading.RLock()
        ## Datos en memoria.
        self._data: dict[str, Any] = {"scene": None, "brightness": None, "scenes": {}}
        ## Temporizador del guardado diferido (None si no hay ninguno pendiente).
        self._timer: threading.Timer | None = None
        ## True si hay cambios en memoria que todavía no se han escrito en disco.
        self._dirty = False
        self.load()

    def load(self) -> None:
        """@brief Lee el archivo; ignora el contenido que no tenga el formato esperado."""
        with self._lock:
            if not self.path.exists():
                return
            try:
                with self.path.open("r", encoding="utf-8") as file:
                    raw = json.load(file)
            except (OSError, ValueError) as exc:
                print(f"Settings: no se pudo leer {self.path} ({exc}); se usan los valores por defecto.", flush=True)
                return
            if not isinstance(raw, dict):
                return

            scene = raw.get("scene")
            brightness = raw.get("brightness")
            scenes = raw.get("scenes")
            self._data["scene"] = scene if isinstance(scene, str) else None
            self._data["brightness"] = (
                brightness if isinstance(brightness, int) and not isinstance(brightness, bool) and 0 <= brightness <= 100
                else None
            )
            if isinstance(scenes, dict):
                self._data["scenes"] = {k: dict(v) for k, v in scenes.items() if isinstance(v, dict)}

    @property
    def scene(self) -> str | None:
        """@brief Escena que estaba activa la última vez, o None."""
        with self._lock:
            return self._data["scene"]

    @property
    def brightness(self) -> int | None:
        """@brief Último brillo guardado (0 a 100), o None si no hay ninguno."""
        with self._lock:
            return self._data["brightness"]

    def scene_settings(self, name: str) -> dict[str, Any]:
        """
        @brief Ajustes guardados de una escena.
        @param name Identificador de la escena.
        @return Copia del diccionario de ajustes (vacío si no hay ninguno).
        """
        with self._lock:
            return dict(self._data["scenes"].get(name, {}))

    def set_scene(self, name: str) -> None:
        """
        @brief Guarda cuál es la escena activa.
        @param name Identificador de la escena.
        """
        with self._lock:
            self._data["scene"] = name
        self.schedule_save()

    def set_brightness(self, value: int) -> None:
        """
        @brief Guarda el brillo.
        @param value Brillo de 0 a 100.
        """
        with self._lock:
            self._data["brightness"] = int(value)
        self.schedule_save()

    def set_scene_settings(self, name: str, values: dict[str, Any]) -> None:
        """
        @brief Guarda los ajustes completos de una escena.
        @param name   Identificador de la escena.
        @param values Diccionario de ajustes (debe ser serializable a JSON).
        """
        with self._lock:
            self._data["scenes"][name] = dict(values)
        self.schedule_save()

    def schedule_save(self, delay: float = SAVE_DELAY_SECONDS) -> None:
        """
        @brief Programa un guardado dentro de `delay` segundos (reinicia el temporizador si ya había uno).
        @param delay Segundos de espera.
        """
        with self._lock:
            self._dirty = True
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(delay, self.flush)
            self._timer.daemon = True
            self._timer.start()

    def flush(self) -> None:
        """
        @brief Escribe los datos en disco ahora mismo, de forma atómica, si hay cambios pendientes.

        Se escribe en un archivo temporal y luego se reemplaza el original, para que un
        corte de luz no deje el JSON a medias. Si el programa corre como root, el archivo
        se deja a nombre del dueño de la carpeta para poder editarlo sin sudo.
        """
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            if not self._dirty:
                return
            tmp = self.path.with_name(self.path.name + ".tmp")
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with tmp.open("w", encoding="utf-8") as file:
                    json.dump(self._data, file, indent=2, ensure_ascii=False)
                self._match_owner(tmp)
                os.replace(tmp, self.path)
                self._dirty = False
            except OSError as exc:
                print(f"Settings: no se pudo guardar {self.path}: {exc}", flush=True)

    def _match_owner(self, file: Path) -> None:
        """
        @brief Si somos root, cambia el dueño del archivo al de su carpeta.
        @param file Archivo a ajustar.
        """
        if not hasattr(os, "geteuid") or os.geteuid() != 0:
            return
        try:
            stat = self.path.parent.stat()
            os.chown(file, stat.st_uid, stat.st_gid)
        except OSError:
            pass