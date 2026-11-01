"""
@file preview.py
@brief Publica el último fotograma dibujado para que la interfaz web lo muestre en vivo.
"""
from __future__ import annotations

import threading
from io import BytesIO

from PIL import Image


class FramePublisher:
    """
    @brief Guarda el último fotograma y lo convierte a PNG solo cuando alguien lo pide.

    El bucle principal llama a publish() en cada fotograma (solo guarda una referencia,
    es muy barato) y el servidor web llama a png() unas pocas veces por segundo.
    """

    def __init__(self) -> None:
        """@brief Crea el publicador sin ningún fotograma."""
        ## Cerrojo que protege el fotograma y la caché del PNG.
        self._lock = threading.Lock()
        ## Último fotograma publicado.
        self._image: Image.Image | None = None
        ## PNG ya codificado del fotograma actual.
        self._png: bytes | None = None
        ## Fotograma del que procede el PNG en caché.
        self._png_source: Image.Image | None = None

    def publish(self, image: Image.Image) -> None:
        """
        @brief Registra el fotograma que se acaba de mostrar en la matriz.
        @param image Fotograma (no se copia; no debe modificarse después).
        """
        with self._lock:
            self._image = image

    def png(self) -> bytes | None:
        """
        @brief Devuelve el fotograma actual codificado como PNG.

        Si el fotograma no ha cambiado desde la última petición (p. ej. con la música en
        pausa) se reutiliza el PNG anterior.

        @return Bytes del PNG, o None si todavía no se ha publicado ningún fotograma.
        """
        with self._lock:
            image = self._image
            if image is None:
                return None
            if image is self._png_source and self._png is not None:
                return self._png
        buffer = BytesIO()
        image.convert("RGB").save(buffer, format="PNG")
        data = buffer.getvalue()
        with self._lock:
            self._png, self._png_source = data, image
        return data