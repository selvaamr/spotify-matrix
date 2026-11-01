"""
@file pixel_art.py
@brief Escena "Pixel art": muestra una imagen (fija o GIF animado) de la galería del usuario.

La imagen que se ve se elige a mano en la web (ajuste "Imagen"). Las imágenes se suben y se borran
desde la página /imagenes (ver web/pixelart_api.py) y se guardan ya convertidas a 64x64 (core/pixelart.py).
Solo la imagen en uso está en memoria. Los GIF se reproducen con su propio ritmo, y una imagen fija
devuelve siempre el mismo fotograma, así que la CPU no trabaja.
"""
from __future__ import annotations

from PIL import Image, ImageDraw

from core.pixelart import PixelArtStore, label_of
from core.scene import Scene
from scenes.pixeltext import draw_centered

## Lado (en píxeles) de los fotogramas guardados.
REF_SIZE = 64


class PixelArtScene(Scene):
    """
    @brief Escena "Pixel art".

    @par Ajustes
    - image: imagen a mostrar, entre las que haya en la galería (la lista se actualiza sola al subir o borrar).
    """

    ## Identificador de la escena.
    name = "pixel_art"
    ## Nombre visible en la interfaz.
    label = "Pixel art"

    def __init__(self, store: PixelArtStore) -> None:
        """
        @brief Crea la escena.
        @param store Galería de imágenes.
        """
        ## Galería de imágenes.
        self.store = store
        ## Versión de la galería con la que se calculó la lista de opciones.
        self._store_version = -1
        ## Identificadores de las imágenes (se vuelven a leer del disco solo cuando cambia la galería).
        self._ids: list[str] = []
        ## Esquema de ajustes de esta escena: la lista de imágenes cambia mientras el programa está en marcha.
        self.settings_schema = self._build_schema()
        super().__init__()
        ## Identificador de la imagen cargada en memoria (None si no hay ninguna).
        self._loaded_id: str | None = None
        ## Fotogramas de la imagen cargada.
        self._frames: list[Image.Image] = []
        ## Duración de cada fotograma, en segundos.
        self._durations: list[float] = []
        ## Segundos transcurridos dentro de la animación.
        self._t = 0.0
        ## Fotograma que muestra la pantalla cuando no hay imágenes.
        self._empty: Image.Image | None = None
        self._refresh()

    def _build_schema(self) -> dict:
        """
        @brief Construye el esquema de ajustes con las imágenes que hay ahora mismo.
        @return Esquema para la interfaz (un selector de imagen).
        """
        ids = self._ids = self.store.ids()
        self._store_version = self.store.version
        return {
            "image": {
                "type": "choice",
                "default": ids[0] if ids else "",
                "label": "Imagen",
                "choices": [{"value": image_id, "label": label_of(image_id)} for image_id in ids],
            }
        }

    def _refresh(self) -> None:
        """
        @brief Pone al día la lista de opciones y la imagen cargada si la galería o la elección han cambiado.

        Se llama en cada fotograma, así que no toca el disco salvo que la galería haya cambiado.

        Si la imagen elegida ya no existe (porque se borró) se pasa a la primera que quede.
        """
        if self.store.version != self._store_version:
            self.settings_schema = self._build_schema()
            self._loaded_id = None
        ids = self._ids
        wanted = self.settings.get("image")
        if wanted not in ids:
            wanted = ids[0] if ids else ""
            self.settings["image"] = wanted
        if wanted != self._loaded_id:
            self._loaded_id = wanted
            self._t = 0.0
            self._frames, self._durations = [], []
            if wanted:
                try:
                    frames, durations = self.store.load(wanted)
                    self._frames, self._durations = frames, [ms / 1000 for ms in durations]
                except KeyError:
                    self._loaded_id = None

    def on_enter(self) -> None:
        """@brief Al activarse la escena, reinicia la animación y refresca la galería."""
        self._refresh()
        self._t = 0.0

    def update(self, dt: float) -> None:
        """
        @brief Avanza la animación (si la imagen es un GIF) y atiende cambios en la galería.
        @param dt Segundos desde el fotograma anterior.
        """
        self._refresh()
        if len(self._frames) > 1:
            self._t += dt

    def render(self, size: int) -> Image.Image:
        """
        @brief Devuelve el fotograma actual de la imagen elegida.
        @param size Lado del fotograma en píxeles (las imágenes están hechas para 64 y se amplían sin suavizar).
        @return Fotograma RGB. Es un objeto compartido: no hay que modificarlo.
        """
        if not self._frames:
            frame = self._empty_frame()
        else:
            frame = self._frames[self._frame_index()]
        if size != REF_SIZE:
            frame = frame.resize((size, size), Image.Resampling.NEAREST)
        return frame

    def _frame_index(self) -> int:
        """
        @brief Fotograma de la animación que toca ahora.
        @return Índice dentro de self._frames.
        """
        if len(self._frames) == 1:
            return 0
        local = self._t % sum(self._durations)
        for index, duration in enumerate(self._durations):
            if local < duration:
                return index
            local -= duration
        return len(self._frames) - 1

    def _empty_frame(self) -> Image.Image:
        """
        @brief Pantalla cuando no hay ninguna imagen en la galería.
        @return Fotograma RGB de 64x64 (se dibuja una vez y se reutiliza).
        """
        if self._empty is None:
            self._empty = Image.new("RGB", (REF_SIZE, REF_SIZE), (0, 0, 0))
            draw = ImageDraw.Draw(self._empty)
            draw_centered(draw, REF_SIZE / 2, 27, "SIN", 1, (110, 110, 110))
            draw_centered(draw, REF_SIZE / 2, 34, "IMAGENES", 1, (110, 110, 110))
        return self._empty
