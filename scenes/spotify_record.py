"""
@file spotify_record.py
@brief Escena que muestra la carátula del disco actual girando como un vinilo.
"""
from __future__ import annotations
from typing import TYPE_CHECKING
from PIL import Image, ImageDraw, ImageOps
from core.scene import Scene

if TYPE_CHECKING:
    from services.spotify import SpotifyPoller


def render_record(art: Image.Image | None, angle: float, size: int) -> Image.Image:
    """
    @brief Dibuja la carátula como un disco circular rotado.
    @param art   Carátula del álbum (None para un fotograma negro).
    @param angle Ángulo de giro en grados.
    @param size  Lado del fotograma en píxeles.
    @return Fotograma RGB de size x size.
    """
    frame = Image.new("RGBA", (size, size), (0, 0, 0, 255))
    if art is None:
        return frame.convert("RGB")

    margin = max(2, size // 32)
    disc_size = size - margin * 2
    # La carátula es la superficie del disco: se rota primero y luego se recorta en círculo.
    art_square = ImageOps.fit(art, (disc_size, disc_size), method=Image.Resampling.LANCZOS)
    rotated = art_square.rotate(angle, resample=Image.Resampling.BICUBIC)

    disc_mask = Image.new("L", (disc_size, disc_size), 0)
    ImageDraw.Draw(disc_mask).ellipse((0, 0, disc_size - 1, disc_size - 1), fill=255)
    frame.paste(rotated.convert("RGBA"), (margin, margin), disc_mask)

    draw = ImageDraw.Draw(frame, "RGBA")
    outer = (margin, margin, size - margin - 1, size - margin - 1)
    draw.ellipse(outer, outline=(6, 6, 6, 255), width=max(1, size // 32))

    center = size // 2
    label_radius = max(5, size // 11)
    hole_radius = max(2, size // 25)
    draw.ellipse(
        (center - label_radius, center - label_radius, center + label_radius, center + label_radius),
        fill=(16, 16, 16, 210),
        outline=(220, 220, 220, 90),
    )
    draw.ellipse(
        (center - hole_radius, center - hole_radius, center + hole_radius, center + hole_radius),
        fill=(0, 0, 0, 255),
    )
    return frame.convert("RGB")


def render_idle(size: int) -> Image.Image:
    """
    @brief Dibuja un disco vacío (contorno gris) para cuando no suena nada.
    @param size Lado del fotograma en píxeles.
    @return Fotograma RGB de size x size.
    """
    frame = Image.new("RGB", (size, size), (0, 0, 0))
    draw = ImageDraw.Draw(frame)
    margin = max(2, size // 32)
    draw.ellipse((margin, margin, size - margin - 1, size - margin - 1), outline=(55, 55, 55), width=2)
    center = size // 2
    radius = max(3, size // 18)
    draw.ellipse((center - radius, center - radius, center + radius, center + radius), fill=(18, 18, 18))
    return frame


def demo_album_art(size: int) -> Image.Image:
    """
    @brief Genera una carátula de ejemplo de cuatro colores, para pruebas.
    @param size Lado de la imagen en píxeles.
    @return Imagen RGB de size x size.
    """
    image = Image.new("RGB", (size, size), (18, 18, 18))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, size // 2, size // 2), fill=(238, 70, 60))
    draw.rectangle((size // 2, 0, size, size // 2), fill=(245, 180, 40))
    draw.rectangle((0, size // 2, size // 2, size), fill=(35, 150, 235))
    draw.rectangle((size // 2, size // 2, size, size), fill=(65, 185, 95))
    draw.line((0, 0, size, size), fill=(255, 255, 255), width=max(2, size // 18))
    draw.line((size, 0, 0, size), fill=(0, 0, 0), width=max(2, size // 22))
    return image


class SpotifyRecordScene(Scene):
    """
    @brief Escena "Disco de Spotify": la carátula gira mientras la música suena.

    @par Ajustes
    - rpm: velocidad de giro en revoluciones por minuto (1 a 120).
    """

    ## Identificador de la escena.
    name = "spotify_record"
    ## Nombre visible en la interfaz.
    label = "Disco de Spotify"
    ## Ajustes configurables por el usuario.
    settings_schema = {
        "rpm": {"type": "float", "min": 1.0, "max": 120.0, "default": 20.0, "label": "Velocidad (rpm)"},
    }

    def __init__(self, poller: "SpotifyPoller", rpm: float = 20.0) -> None:
        """
        @brief Crea la escena.
        @param poller Fuente de la carátula y del estado de reproducción.
        @param rpm    Velocidad inicial de giro.
        """
        super().__init__()
        ## Fuente de datos de Spotify.
        self.poller = poller
        self.settings["rpm"] = rpm
        ## Ángulo actual del disco en grados.
        self.angle = 0.0
        ## Última carátula leída del poller.
        self._image: Image.Image | None = None

    def update(self, dt: float) -> None:
        """
        @brief Lee el estado de Spotify y gira el disco si hay música sonando.
        @param dt Segundos desde el fotograma anterior.
        """
        self._image, is_playing = self.poller.snapshot()
        if is_playing and self._image is not None:
            self.angle = (self.angle - 360.0 * (self.settings["rpm"] / 60.0) * dt) % 360.0

    def render(self, size: int) -> Image.Image:
        """
        @brief Dibuja el disco girando, o el disco vacío si no hay carátula.
        @param size Lado del fotograma en píxeles.
        @return Fotograma RGB.
        """
        if self._image is None:
            return render_idle(size)
        return render_record(self._image, self.angle, size)