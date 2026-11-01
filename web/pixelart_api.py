"""
@file pixelart_api.py
@brief API REST de la galería de pixel art y su página de gestión (/imagenes).

Se monta sobre la aplicación principal con app.include_router(), así server.py no cambia. Las imágenes
se envían en base64 dentro de un JSON (así no hace falta instalar python-multipart).

@par Endpoints
| Método | Ruta                       | Qué hace                                                                  |
|--------|----------------------------|---------------------------------------------------------------------------|
| GET    | /imagenes                  | Página para ver, subir y borrar imágenes (HTML)                           |
| GET    | /api/pixelart              | Lista de imágenes y máximo permitido                                      |
| POST   | /api/pixelart/preview      | Convierte sin guardar y devuelve el resultado (PNG en base64)             |
| POST   | /api/pixelart              | Convierte y guarda. Cuerpo: {"name", "data"}                              |
| GET    | /api/pixelart/{id}/image   | Imagen ya convertida (PNG o GIF)                                          |
| DELETE | /api/pixelart/{id}         | Borra una imagen                                                          |
"""
import base64
import binascii
import io
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from core.pixelart import MAX_FILE_BYTES, MAX_IMAGES, PixelArtError, PixelArtStore, convert

## Página de gestión de imágenes.
PAGE = Path(__file__).parent / "static" / "imagenes.html"


class UploadRequest(BaseModel):
    """@brief Cuerpo de POST /api/pixelart y /api/pixelart/preview."""

    ## Nombre de la imagen (solo se usa al guardar).
    name: str = "imagen"
    ## Contenido del archivo en base64 (con o sin el prefijo "data:...;base64,").
    data: str


def _decode(body: UploadRequest) -> bytes:
    """
    @brief Decodifica el base64 del archivo subido.
    @param body Cuerpo de la petición.
    @return Bytes del archivo.
    @throws HTTPException 400 si el base64 no es válido y 413 si el archivo es demasiado grande.
    """
    text = body.data.split(",", 1)[1] if body.data.startswith("data:") else body.data
    if len(text) > MAX_FILE_BYTES * 4 // 3 + 16:
        raise HTTPException(status_code=413, detail=f"El archivo pesa demasiado (máximo {MAX_FILE_BYTES // (1024 * 1024)} MB).")
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="El archivo no es válido.")


def create_pixelart_router(store: PixelArtStore) -> APIRouter:
    """
    @brief Construye el router con las rutas de la galería.
    @param store Galería de imágenes.
    @return Router de FastAPI listo para incluir en la aplicación.
    """
    router = APIRouter()

    @router.get("/imagenes", include_in_schema=False)
    def images_page() -> FileResponse:
        """@brief Devuelve la página de gestión de imágenes."""
        return FileResponse(PAGE)

    @router.get("/api/pixelart")
    def list_images() -> dict[str, Any]:
        """@brief Devuelve las imágenes y el máximo permitido."""
        return {"images": store.describe(), "max": MAX_IMAGES}

    @router.post("/api/pixelart/preview")
    def preview(body: UploadRequest) -> dict[str, Any]:
        """
        @brief Convierte una imagen sin guardarla, para ver cómo quedará.
        @param body Archivo subido.
        @return {"image": PNG en base64 (primer fotograma), "frames": número de fotogramas}.
        @throws HTTPException 400 si la imagen no se puede procesar.
        """
        try:
            frames, _ = convert(_decode(body))
        except PixelArtError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        buffer = io.BytesIO()
        frames[0].save(buffer, "PNG")
        return {"image": base64.b64encode(buffer.getvalue()).decode("ascii"), "frames": len(frames)}

    @router.post("/api/pixelart")
    def add_image(body: UploadRequest) -> dict[str, Any]:
        """
        @brief Convierte y guarda una imagen.
        @param body Nombre y archivo.
        @return {"id": identificador de la imagen guardada}.
        @throws HTTPException 400 si no se puede procesar o se ha alcanzado el máximo de imágenes.
        """
        try:
            return {"id": store.add(body.name, _decode(body))}
        except PixelArtError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @router.get("/api/pixelart/{image_id}/image")
    def get_image(image_id: str) -> FileResponse:
        """
        @brief Devuelve el archivo ya convertido de una imagen.
        @param image_id Identificador.
        @throws HTTPException 404 si no existe.
        """
        try:
            return FileResponse(store.path_of(image_id), headers={"Cache-Control": "no-cache"})
        except KeyError:
            raise HTTPException(status_code=404, detail="La imagen no existe.")

    @router.delete("/api/pixelart/{image_id}")
    def delete_image(image_id: str) -> dict[str, bool]:
        """
        @brief Borra una imagen.
        @param image_id Identificador.
        @return {"ok": true}
        @throws HTTPException 404 si no existe.
        """
        try:
            store.delete(image_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="La imagen no existe.")
        return {"ok": True}

    return router
