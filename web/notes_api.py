"""
@file notes_api.py
@brief API REST de las notas del calendario y su página de gestión (/notas).

Se monta sobre la aplicación principal con app.include_router(), así server.py no cambia.

@par Endpoints
| Método | Ruta              | Qué hace                                                               |
|--------|-------------------|------------------------------------------------------------------------|
| GET    | /notas            | Página para ver, crear, editar y borrar notas (HTML)                   |
| GET    | /api/notes        | Notas ordenadas, repeticiones, colores disponibles y leyenda           |
| POST   | /api/notes        | Crea una nota. Cuerpo: {"text", "date", "time", "repeat", "color"}     |
| PUT    | /api/notes/{id}   | Modifica una nota (mismo cuerpo)                                       |
| DELETE | /api/notes/{id}   | Borra una nota                                                         |
| PUT    | /api/notes-legend | Cambia la leyenda de colores. Cuerpo: {"legend": {"green": "Trabajo"}} |
| GET    | /api/notes-days   | Qué notas caen cada día de un periodo: ?start=YYYY-MM-DD&end=YYYY-MM-DD |
| PUT    | /api/notes-view-day | Día que muestra la matriz. Cuerpo: {"day": "YYYY-MM-DD"} ("" = hoy)  |
"""
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from core.notes import (
    DEFAULT_NOTE_COLOR, MAX_LEGEND_LENGTH, MAX_TEXT_LENGTH, NOTE_COLORS, REPEATS, NotesStore,
)
from scenes.pixeltext import hex_color

## Máximo de días que se pueden pedir de una vez a /api/notes-days (6 semanas de calendario y algo más).
MAX_DAYS_RANGE = 62

## Página de gestión de notas.
NOTES_PAGE = Path(__file__).parent / "static" / "notas.html"


class NoteRequest(BaseModel):
    """@brief Cuerpo de POST /api/notes y PUT /api/notes/{id}."""

    ## Texto de la nota.
    text: str
    ## Fecha (YYYY-MM-DD).
    date: str
    ## Hora (HH:MM) o cadena vacía si es de todo el día.
    time: str = ""
    ## Repetición: none, daily, weekly, monthly o yearly.
    repeat: str = "none"
    ## Color del punto de la nota (green, white, cyan...).
    color: str = DEFAULT_NOTE_COLOR


class ViewDayRequest(BaseModel):
    """@brief Cuerpo de PUT /api/notes-view-day."""

    ## Día que muestra la matriz (YYYY-MM-DD), o cadena vacía para seguir siempre el de hoy.
    day: str = ""


class LegendRequest(BaseModel):
    """@brief Cuerpo de PUT /api/notes-legend."""

    ## Color -> significado (cadena vacía para quitarlo).
    legend: dict[str, str]


def create_notes_router(store: NotesStore) -> APIRouter:
    """
    @brief Construye el router con las rutas de las notas.
    @param store Almacén de notas.
    @return Router de FastAPI listo para incluir en la aplicación.
    """
    router = APIRouter()

    @router.get("/notas", include_in_schema=False)
    def notes_page() -> FileResponse:
        """@brief Devuelve la página de gestión de notas."""
        return FileResponse(NOTES_PAGE)

    @router.get("/api/notes")
    def list_notes() -> dict[str, Any]:
        """@brief Devuelve todas las notas, las opciones de repetición, los colores y la leyenda."""
        return {
            "notes": [asdict(note) for note in store.all()],
            "repeats": [{"value": key, "label": label} for key, label in REPEATS.items()],
            "colors": [{"value": key, "label": name, "color": hex_color(rgb)} for key, (name, rgb) in NOTE_COLORS.items()],
            "default_color": DEFAULT_NOTE_COLOR,
            "legend": store.legend(),
            "view_day": store.view_day(),
            "max_length": MAX_TEXT_LENGTH,
            "max_legend_length": MAX_LEGEND_LENGTH,
        }

    @router.post("/api/notes")
    def create_note(body: NoteRequest) -> dict[str, Any]:
        """
        @brief Crea una nota.
        @param body Datos de la nota.
        @return La nota creada.
        @throws HTTPException 400 si algún campo no es válido.
        """
        try:
            return asdict(store.add(body.text, body.date, body.time, body.repeat, body.color))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @router.put("/api/notes/{note_id}")
    def edit_note(note_id: str, body: NoteRequest) -> dict[str, Any]:
        """
        @brief Modifica una nota.
        @param note_id Identificador de la nota.
        @param body    Datos nuevos.
        @return La nota modificada.
        @throws HTTPException 404 si no existe, 400 si algún campo no es válido.
        """
        try:
            return asdict(store.update(note_id, body.text, body.date, body.time, body.repeat, body.color))
        except KeyError:
            raise HTTPException(status_code=404, detail="La nota no existe.")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @router.delete("/api/notes/{note_id}")
    def remove_note(note_id: str) -> dict[str, bool]:
        """
        @brief Borra una nota.
        @param note_id Identificador de la nota.
        @return {"ok": true}
        @throws HTTPException 404 si no existe.
        """
        try:
            store.delete(note_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="La nota no existe.")
        return {"ok": True}

    @router.get("/api/notes-days")
    def notes_days(start: str, end: str) -> dict[str, Any]:
        """
        @brief Dice qué notas caen cada día de un periodo, teniendo en cuenta las repeticiones.

        Lo usa el calendario de la página /notas para marcar los días con notas.

        @param start Primer día (YYYY-MM-DD).
        @param end   Último día (YYYY-MM-DD), incluido.
        @return {"days": {"YYYY-MM-DD": [ids de las notas, por hora]}}; solo los días con alguna nota.
        @throws HTTPException 400 si las fechas no son válidas o el periodo es demasiado largo.
        """
        try:
            first, last = date.fromisoformat(start), date.fromisoformat(end)
        except ValueError:
            raise HTTPException(status_code=400, detail="La fecha no es válida.")
        if last < first or (last - first).days >= MAX_DAYS_RANGE:
            raise HTTPException(status_code=400, detail="El periodo no es válido.")
        days = {}
        day = first
        while day <= last:
            ids = [note.id for note in store.on_day(day)]
            if ids:
                days[day.isoformat()] = ids
            day += timedelta(days=1)
        return {"days": days}

    @router.put("/api/notes-view-day")
    def edit_view_day(body: ViewDayRequest) -> dict[str, str]:
        """
        @brief Elige el día que muestra la matriz en la escena de calendario.
        @param body Día (YYYY-MM-DD), o cadena vacía para seguir el de hoy.
        @return {"view_day": valor guardado}
        @throws HTTPException 400 si la fecha no es válida.
        """
        try:
            return {"view_day": store.set_view_day(body.day)}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @router.put("/api/notes-legend")
    def edit_legend(body: LegendRequest) -> dict[str, Any]:
        """
        @brief Cambia lo que significa cada color.
        @param body Color -> significado.
        @return {"legend": leyenda guardada}
        @throws HTTPException 400 si no es válida.
        """
        try:
            return {"legend": store.set_legend(body.legend)}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    return router
