"""
@file notes.py
@brief Notas y recordatorios del calendario, guardados en un archivo JSON (notes.json).

Cada nota tiene un texto, una fecha, una hora opcional y una repetición (nunca, cada día, cada
semana, cada mes o cada año). La escena de calendario en estilo "3 días" pregunta aquí qué notas
caen en cada día, y la web las crea, edita y borra a través de web/notes_api.py.

El guardado es atómico (archivo temporal + reemplazo) para que un corte de luz no deje el JSON a
medias, y el almacén es seguro entre hilos (servidor web y bucle principal).
"""
from __future__ import annotations

import calendar
import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

## Repeticiones permitidas: identificador -> texto para la interfaz.
REPEATS = {
    "none": "No se repite",
    "daily": "Cada día",
    "weekly": "Cada semana",
    "monthly": "Cada mes",
    "yearly": "Cada año",
}

## Longitud máxima del texto de una nota.
MAX_TEXT_LENGTH = 60


@dataclass(frozen=True)
class Note:
    """
    @brief Una nota o recordatorio.
    """

    ## Identificador único (8 caracteres hexadecimales).
    id: str
    ## Texto de la nota.
    text: str
    ## Fecha de la primera vez (YYYY-MM-DD). Las repeticiones cuentan a partir de ella.
    date: str
    ## Hora (HH:MM), o cadena vacía si la nota es de todo el día.
    time: str
    ## Repetición: "none", "daily", "weekly", "monthly" o "yearly".
    repeat: str

    def occurs_on(self, day: date) -> bool:
        """
        @brief Indica si la nota cae en un día concreto, teniendo en cuenta la repetición.

        Las notas mensuales del 29, 30 o 31 caen el último día de los meses más cortos, y las
        anuales del 29 de febrero caen el 28 de febrero en los años no bisiestos.

        @param day Día a comprobar.
        @return True si la nota se muestra ese día.
        """
        start = date.fromisoformat(self.date)
        if day < start:
            return False
        if self.repeat == "daily":
            return True
        if self.repeat == "weekly":
            return day.weekday() == start.weekday()
        if self.repeat == "monthly":
            return day.day == min(start.day, calendar.monthrange(day.year, day.month)[1])
        if self.repeat == "yearly":
            if day.month != start.month:
                return False
            return day.day == min(start.day, calendar.monthrange(day.year, day.month)[1])
        return day == start


def validate(text: str, day: str, time: str, repeat: str) -> tuple[str, str, str, str]:
    """
    @brief Comprueba y normaliza los campos de una nota.
    @param text   Texto de la nota.
    @param day    Fecha en formato YYYY-MM-DD.
    @param time   Hora en formato HH:MM, o cadena vacía.
    @param repeat Repetición.
    @return Tupla (texto, fecha, hora, repetición) ya normalizada.
    @throws ValueError con un mensaje en español si algún campo no es válido.
    """
    text = " ".join(str(text).split())
    if not text:
        raise ValueError("El texto no puede estar vacío.")
    if len(text) > MAX_TEXT_LENGTH:
        raise ValueError(f"El texto es demasiado largo (máximo {MAX_TEXT_LENGTH} caracteres).")
    try:
        day = date.fromisoformat(str(day)).isoformat()
    except ValueError:
        raise ValueError("La fecha no es válida.") from None
    time = str(time or "").strip()
    if time:
        parts = time.split(":")
        if len(parts) != 2 or not all(part.isdigit() for part in parts) or not (0 <= int(parts[0]) <= 23 and 0 <= int(parts[1]) <= 59):
            raise ValueError("La hora no es válida (usa HH:MM).")
        time = f"{int(parts[0]):02d}:{int(parts[1]):02d}"
    if repeat not in REPEATS:
        raise ValueError("La repetición no es válida.")
    return text, day, time, repeat


class NotesStore:
    """
    @brief Almacén de notas con persistencia en JSON.
    """

    def __init__(self, path: Path = Path("notes.json")) -> None:
        """
        @brief Crea el almacén y carga el archivo si existe.
        @param path Ruta del archivo JSON.
        """
        ## Ruta del archivo JSON.
        self.path = path
        ## Cerrojo que protege los datos.
        self._lock = threading.RLock()
        ## Notas en memoria, por identificador.
        self._notes: dict[str, Note] = {}
        ## Contador que sube con cada cambio; las escenas lo usan para saber cuándo volver a dibujar.
        self.version = 0
        self.load()

    def load(self) -> None:
        """
        @brief Lee el archivo. Si está corrupto lo aparta como notes.json.bad y empieza vacío.

        Las notas con campos no válidos se descartan una a una, sin perder las demás.
        """
        with self._lock:
            self._notes = {}
            if not self.path.exists():
                return
            try:
                with self.path.open("r", encoding="utf-8") as file:
                    raw = json.load(file)
                items = raw["notes"] if isinstance(raw, dict) else raw
                if not isinstance(items, list):
                    raise ValueError("formato inesperado")
            except (OSError, ValueError, KeyError) as exc:
                backup = self.path.with_name(self.path.name + ".bad")
                try:
                    os.replace(self.path, backup)
                except OSError:
                    pass
                print(f"Notas: no se pudo leer {self.path} ({exc}); se guarda como {backup.name} y se empieza vacío.", flush=True)
                return
            for item in items:
                try:
                    text, day, time, repeat = validate(item["text"], item["date"], item.get("time", ""), item.get("repeat", "none"))
                    note_id = str(item.get("id") or uuid.uuid4().hex[:8])
                    self._notes[note_id] = Note(note_id, text, day, time, repeat)
                except (KeyError, TypeError, ValueError, AttributeError):
                    continue
            self.version += 1

    def all(self) -> list[Note]:
        """
        @brief Todas las notas, ordenadas por fecha y hora.
        @return Lista de notas (copia).
        """
        with self._lock:
            return sorted(self._notes.values(), key=lambda note: (note.date, note.time, note.text))

    def on_day(self, day: date) -> list[Note]:
        """
        @brief Notas que caen en un día, con las de todo el día primero y luego por hora.
        @param day Día a consultar.
        @return Lista de notas (copia).
        """
        with self._lock:
            found = [note for note in self._notes.values() if note.occurs_on(day)]
        return sorted(found, key=lambda note: (note.time != "", note.time, note.text))

    def add(self, text: str, day: str, time: str = "", repeat: str = "none") -> Note:
        """
        @brief Crea una nota y la guarda.
        @param text   Texto de la nota.
        @param day    Fecha (YYYY-MM-DD).
        @param time   Hora (HH:MM) o vacío.
        @param repeat Repetición.
        @return La nota creada.
        @throws ValueError si algún campo no es válido.
        """
        text, day, time, repeat = validate(text, day, time, repeat)
        note = Note(uuid.uuid4().hex[:8], text, day, time, repeat)
        with self._lock:
            self._notes[note.id] = note
            self._changed()
        return note

    def update(self, note_id: str, text: str, day: str, time: str = "", repeat: str = "none") -> Note:
        """
        @brief Modifica una nota y la guarda.
        @param note_id Identificador de la nota.
        @param text    Texto nuevo.
        @param day     Fecha nueva.
        @param time    Hora nueva o vacío.
        @param repeat  Repetición nueva.
        @return La nota modificada.
        @throws KeyError si la nota no existe.
        @throws ValueError si algún campo no es válido.
        """
        text, day, time, repeat = validate(text, day, time, repeat)
        with self._lock:
            if note_id not in self._notes:
                raise KeyError(note_id)
            note = Note(note_id, text, day, time, repeat)
            self._notes[note_id] = note
            self._changed()
        return note

    def delete(self, note_id: str) -> None:
        """
        @brief Borra una nota.
        @param note_id Identificador de la nota.
        @throws KeyError si la nota no existe.
        """
        with self._lock:
            del self._notes[note_id]
            self._changed()

    def _changed(self) -> None:
        """@brief Sube la versión y guarda en disco (se llama con el cerrojo tomado)."""
        self.version += 1
        self.flush()

    def flush(self) -> None:
        """
        @brief Escribe las notas en disco de forma atómica.

        Se escribe en un archivo temporal, se fuerza a disco y luego se reemplaza el original. Si el
        programa corre como root, el archivo se deja a nombre del dueño de la carpeta.
        """
        with self._lock:
            tmp = self.path.with_name(self.path.name + ".tmp")
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with tmp.open("w", encoding="utf-8") as file:
                    json.dump({"notes": [asdict(note) for note in self.all()]}, file, indent=2, ensure_ascii=False)
                    file.flush()
                    os.fsync(file.fileno())
                self._match_owner(tmp)
                os.replace(tmp, self.path)
            except OSError as exc:
                print(f"Notas: no se pudo guardar {self.path}: {exc}", flush=True)

    def _match_owner(self, file: Path) -> None:
        """
        @brief Si somos root, cambia el dueño del archivo al de su carpeta.
        @param file Archivo a ajustar.
        """
        if not hasattr(os, "geteuid") or os.geteuid() != 0:
            return
        try:
            stat = self.path.parent.resolve().stat()
            os.chown(file, stat.st_uid, stat.st_gid)
        except OSError:
            pass
