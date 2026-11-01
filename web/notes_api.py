"""
@file notes_api.py
@brief API REST de las notas del calendario y su página de gestión (/notas).

Se monta sobre la aplicación principal con app.include_router(), así server.py no cambia.

@par Endpoints
| Método | Ruta              | Qué hace                                                               |
|--------|-------------------|------------------------------------------------------------------------|
| GET    | /notas            | Página para ver, crear, editar y borrar notas (HTML)                   |
| GET    | /api/notes        | Todas las notas ordenadas, y las repeticiones disponibles              |
| POST   | /api/notes        | Crea una nota. Cuerpo: {"text", "date", "time", "repeat"}              |
| PUT    | /api/notes/{id}   | Modifica una nota (mismo cuerpo)                                       |
| DELETE | /api/notes/{id}   | Borra una nota                                                         |
"""
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from core.notes import MAX_TEXT_LENGTH, REPEATS, NotesStore

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
        """@brief Devuelve todas las notas y las opciones de repetición."""
        return {
            "notes": [asdict(note) for note in store.all()],
            "repeats": [{"value": key, "label": label} for key, label in REPEATS.items()],
            "max_length": MAX_TEXT_LENGTH,
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
            return asdict(store.add(body.text, body.date, body.time, body.repeat))
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
            return asdict(store.update(note_id, body.text, body.date, body.time, body.repeat))
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

    return router
