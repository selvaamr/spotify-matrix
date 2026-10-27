"""
@file test_pattern.py
@brief Escena de prueba: franjas de colores en movimiento para comprobar la matriz.
"""
from __future__ import annotations
from PIL import Image, ImageDraw
from core.scene import Scene


## Colores de las franjas (RGB).
COLORS = (
    (255, 0, 0), (255, 160, 0), (255, 255, 0), (0, 255, 0),
    (0, 120, 255), (80, 0, 255), (255, 255, 255), (0, 0, 0),
)


class TestPatternScene(Scene):
    """
    @brief Franjas de colores que se desplazan horizontalmente, con un marco blanco.

    Útil para verificar cableado, brillo y orientación sin necesitar Spotify.
    """

    ## Identificador de la escena.
    name = "test_pattern"
    ## Nombre visible en la interfaz.
    label = "Patrón de prueba"
    ## Velocidad de desplazamiento en píxeles por segundo.
    speed_px_per_sec = 20.0

    def __init__(self) -> None:
        """@brief Crea la escena con el desplazamiento a cero."""
        super().__init__()
        ## Desplazamiento acumulado en píxeles.
        self.offset = 0.0

    def update(self, dt: float) -> None:
        """
        @brief Desplaza las franjas.
        @param dt Segundos desde el fotograma anterior.
        """
        self.offset += self.speed_px_per_sec * dt

    def render(self, size: int) -> Image.Image:
        """
        @brief Dibuja las franjas con el desplazamiento actual.
        @param size Lado del fotograma en píxeles.
        @return Fotograma RGB.
        """
        offset = int(self.offset) % size
        frame = Image.new("RGB", (size, size), (0, 0, 0))
        draw = ImageDraw.Draw(frame)
        stripe_width = max(1, size // len(COLORS))
        for index, color in enumerate(COLORS):
            x0 = (index * stripe_width + offset) % size
            draw.rectangle((x0, 0, min(size - 1, x0 + stripe_width - 1), size - 1), fill=color)
            if x0 + stripe_width > size:
                draw.rectangle((0, 0, (x0 + stripe_width) % size, size - 1), fill=color)
        draw.rectangle((0, 0, size - 1, size - 1), outline=(255, 255, 255))
        return frame
