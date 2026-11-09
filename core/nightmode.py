"""
@file nightmode.py
@brief Modo noche: la matriz baja al brillo mínimo y todo se ve en rojo, que molesta menos para dormir.

Se coloca entre el controlador y la pantalla real (MatrixDisplay o MockDisplay) y se comporta como
una pantalla más:
  - set_brightness(): guarda el brillo "de día"; mientras es de noche la matriz se queda en NIGHT_BRIGHTNESS.
  - filter(): convierte cada fotograma a rojo (el bucle principal lo aplica antes de mostrarlo y de
    publicarlo en la vista previa de la web, para que la web enseñe lo mismo que la matriz).

Se activa y desactiva solo a las horas programadas (por defecto de 22:00 a 08:00) o a mano desde la
web. Cada vez que entra o sale avisa a las funciones de on_change (main.py lo usa para poner el reloj
con los dos puntos fijos y luego volver al modo anterior). Un cambio a mano se respeta hasta la siguiente hora programada. El horario se guarda en
night.json; el estado manual no (al reiniciar manda el horario).
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageChops

## Brillo de la matriz en modo noche (1 es el mínimo que no apaga los LEDs).
## Si de noche no se ve nada, súbelo a 3 o 5.
NIGHT_BRIGHTNESS = 1

## Intensidad del rojo por defecto en modo noche (porcentaje del color original). Se ajusta desde la web.
DEFAULT_LEVEL = 60

## Intensidad mínima permitida: por debajo, con el brillo al mínimo, los LEDs ya no se encienden.
MIN_LEVEL = 5

## Hora a la que se activa sola, por defecto.
DEFAULT_START = "22:00"

## Hora a la que se desactiva sola, por defecto.
DEFAULT_END = "08:00"


def _validate_time(value: str) -> str:
    """
    @brief Comprueba una hora HH:MM.
    @param value Texto con la hora.
    @return La hora normalizada (HH:MM con dos cifras).
    @throws ValueError si no es una hora válida.
    """
    parts = str(value or "").strip().split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ValueError("La hora no es válida (usa HH:MM).")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("La hora no es válida (usa HH:MM).")
    return f"{hour:02d}:{minute:02d}"


def in_schedule(now: str, start: str, end: str) -> bool:
    """
    @brief Indica si una hora cae dentro del horario de noche (que puede pasar de medianoche).
    @param now   Hora actual (HH:MM).
    @param start Inicio (HH:MM), incluido.
    @param end   Fin (HH:MM), no incluido.
    @return True si es de noche. Si inicio y fin son iguales, nunca lo es.
    """
    if start == end:
        return False
    if start < end:
        return start <= now < end
    return now >= start or now < end


def to_red(frame: Image.Image, level_percent: int = 100) -> Image.Image:
    """
    @brief Convierte un fotograma a rojo: cada píxel toma como brillo el de su canal más intenso.

    Se usa el canal más intenso (y no la luminancia) para que los colores oscuros como el azul no
    desaparezcan con el brillo al mínimo. Además se multiplica por la intensidad elegida: como el
    brillo de la matriz ya está al mínimo, es la única forma de que alumbre todavía menos.

    @param frame         Fotograma RGB.
    @param level_percent Intensidad del rojo (100 = el color original).
    @return Fotograma RGB nuevo, solo con el canal rojo.
    """
    red, green, blue = frame.convert("RGB").split()
    level = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    if level_percent < 100:
        factor = level_percent / 100
        level = level.point(lambda value: int(value * factor + 0.5))
    zero = Image.new("L", frame.size, 0)
    return Image.merge("RGB", (level, zero, zero))


class NightMode:
    """
    @brief Modo noche: envuelve la pantalla real, aplica el horario y el filtro rojo.
    """

    def __init__(
        self,
        display: Any,
        path: Path = Path("night.json"),
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        """
        @brief Crea el modo noche y carga el horario guardado.
        @param display Pantalla real (necesita show(), set_brightness() y clear()).
        @param path    Archivo JSON donde se guarda el horario.
        @param clock   Función que devuelve la hora actual (se puede sustituir en las pruebas).
        """
        ## Pantalla real.
        self.display = display
        ## Archivo del horario.
        self.path = path
        ## Reloj.
        self._clock = clock
        ## Cerrojo (la web cambia el estado desde otro hilo).
        self._lock = threading.RLock()
        ## Si el horario automático está activado.
        self.auto = True
        ## Hora de inicio (HH:MM).
        self.start = DEFAULT_START
        ## Hora de fin (HH:MM).
        self.end = DEFAULT_END
        ## Intensidad del rojo en modo noche (MIN_LEVEL a 100).
        self.level = DEFAULT_LEVEL
        ## Cambio a mano: True (forzado encendido), False (forzado apagado) o None (manda el horario).
        self._manual: bool | None = None
        ## Si el horario decía "noche" en la última comprobación (para saber cuándo cambia).
        self._scheduled = False
        ## Si el modo noche está aplicado ahora mismo.
        self._active = False
        ## Brillo "de día" que ha pedido el usuario.
        self._day_brightness: int | None = None
        ## Funciones a las que se avisa al entrar (True) o salir (False) del modo noche.
        self.on_change: list[Callable[[bool], None]] = []
        ## Último fotograma recibido y su versión en rojo (para no recalcular un fotograma repetido).
        self._last_in: Image.Image | None = None
        self._last_out: Image.Image | None = None
        self._load()
        self._scheduled = self._schedule_now()

    # ------------------------------------------------------------------ #
    #  Estado
    # ------------------------------------------------------------------ #
    def _schedule_now(self) -> bool:
        """@brief Si el horario dice que ahora es de noche."""
        return self.auto and in_schedule(self._clock().strftime("%H:%M"), self.start, self.end)

    def tick(self) -> None:
        """
        @brief Se llama en cada vuelta del bucle principal: aplica el horario y el brillo que toque.

        Cuando el horario cambia (llega la hora de inicio o la de fin), se olvida el cambio a mano.
        """
        with self._lock:
            scheduled = self._schedule_now()
            if scheduled != self._scheduled:
                self._scheduled = scheduled
                self._manual = None
            wanted = self._manual if self._manual is not None else scheduled
            if wanted != self._active:
                self._active = wanted
                self._apply_brightness()
                for callback in self.on_change:
                    try:
                        callback(wanted)
                    except Exception as exc:  # un fallo aquí no debe parar la matriz
                        print(f"Modo noche: error al avisar del cambio: {exc}", flush=True)

    @property
    def active(self) -> bool:
        """@brief Si el modo noche está aplicado ahora mismo."""
        return self._active

    def set_active(self, on: bool) -> None:
        """
        @brief Enciende o apaga el modo noche a mano (se respeta hasta la siguiente hora programada).
        @param on True para encenderlo.
        """
        with self._lock:
            self._manual = bool(on)
            self.tick()

    def set_schedule(self, auto: bool, start: str, end: str) -> None:
        """
        @brief Cambia el horario automático y lo guarda.
        @param auto  Si se activa solo.
        @param start Hora de inicio (HH:MM).
        @param end   Hora de fin (HH:MM).
        @throws ValueError si alguna hora no es válida.
        """
        start, end = _validate_time(start), _validate_time(end)
        with self._lock:
            self.auto, self.start, self.end = bool(auto), start, end
            self._scheduled = self._schedule_now()
            self._manual = None
            self._save()
            self.tick()

    def set_level(self, level: int) -> int:
        """
        @brief Cambia la intensidad del rojo y la guarda. Se nota al momento si es de noche.
        @param level Intensidad (se limita entre MIN_LEVEL y 100).
        @return Intensidad aplicada.
        """
        with self._lock:
            self.level = max(MIN_LEVEL, min(100, int(level)))
            self._last_in = self._last_out = None  # el siguiente fotograma se recalcula y se reenvía
            self._save()
            return self.level

    def state(self) -> dict[str, Any]:
        """
        @brief Estado para la web.
        @return {"active", "auto", "start", "end", "level", "min_level"}.
        """
        with self._lock:
            return {
                "active": self._active, "auto": self.auto, "start": self.start, "end": self.end,
                "level": self.level, "min_level": MIN_LEVEL,
            }

    # ------------------------------------------------------------------ #
    #  Pantalla
    # ------------------------------------------------------------------ #
    def filter(self, frame: Image.Image) -> Image.Image:
        """
        @brief Devuelve el fotograma tal cual de día, o en rojo de noche.

        Si llega el mismo objeto que la vez anterior se devuelve el mismo resultado (también el mismo
        objeto), así la pantalla sigue sabiendo que no ha cambiado y no lo reenvía.

        @param frame Fotograma de la escena.
        @return Fotograma a mostrar.
        """
        if not self._active:
            return frame
        with self._lock:
            if frame is not self._last_in or self._last_out is None:
                self._last_in, self._last_out = frame, to_red(frame, self.level)
            return self._last_out

    def show(self, image: Image.Image) -> None:
        """
        @brief Muestra un fotograma (ya filtrado con filter()) en la pantalla real.
        @param image Fotograma.
        """
        self.display.show(image)

    def set_brightness(self, value: int) -> None:
        """
        @brief Guarda el brillo de día; solo se aplica a la matriz si no es de noche.
        @param value Brillo de 0 a 100.
        """
        with self._lock:
            self._day_brightness = int(value)
            if not self._active:
                self.display.set_brightness(value)

    def clear(self) -> None:
        """@brief Apaga los LEDs."""
        self.display.clear()

    def _apply_brightness(self) -> None:
        """@brief Pone en la matriz el brillo de noche o el de día, según toque."""
        self._last_in = self._last_out = None
        if self._active:
            self.display.set_brightness(NIGHT_BRIGHTNESS)
        elif self._day_brightness is not None:
            self.display.set_brightness(self._day_brightness)

    # ------------------------------------------------------------------ #
    #  Persistencia
    # ------------------------------------------------------------------ #
    def _load(self) -> None:
        """@brief Lee el horario guardado (si no existe o está mal, se usan los valores por defecto)."""
        try:
            with self.path.open("r", encoding="utf-8") as file:
                raw = json.load(file)
            self.auto = bool(raw.get("auto", True))
            self.start = _validate_time(raw.get("start", DEFAULT_START))
            self.end = _validate_time(raw.get("end", DEFAULT_END))
            self.level = max(MIN_LEVEL, min(100, int(raw.get("level", DEFAULT_LEVEL))))
        except (OSError, ValueError, TypeError, AttributeError):
            self.auto, self.start, self.end, self.level = True, DEFAULT_START, DEFAULT_END, DEFAULT_LEVEL

    def _save(self) -> None:
        """@brief Guarda el horario de forma atómica (archivo temporal + reemplazo)."""
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            with tmp.open("w", encoding="utf-8") as file:
                json.dump({"auto": self.auto, "start": self.start, "end": self.end, "level": self.level}, file, indent=2)
                file.flush()
                os.fsync(file.fileno())
            if hasattr(os, "geteuid") and os.geteuid() == 0:
                try:
                    stat = self.path.parent.resolve().stat()
                    os.chown(tmp, stat.st_uid, stat.st_gid)
                except OSError:
                    pass
            os.replace(tmp, self.path)
        except OSError as exc:
            print(f"Modo noche: no se pudo guardar {self.path}: {exc}", flush=True)
