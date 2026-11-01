"""
@file calendar_scene.py
@brief Escena de calendario con dos estilos: tres semanas alrededor de hoy, o el día en grande.

Está pensada para una matriz de 64x64 con una estructura circular delante. Un mes completo con
números de dos cifras no cabe dentro de un círculo, así que el estilo "Semanas" muestra la semana
actual con la anterior y la siguiente, y el estilo "Día" muestra la fecha de hoy a lo grande.
La semana empieza en lunes.

La imagen solo cambia al cambiar de día, así que la CPU apenas trabaja.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Callable

from PIL import Image, ImageDraw

from core.scene import Scene
from scenes.pixeltext import (
    COLORS, DAY_INITIALS, DAYS_FULL, MONTHS, MONTHS_FULL, Color, dim, draw_centered, draw_text, hex_color, text_width,
)

## Lado (en píxeles) para el que están pensados todos los diseños.
REF_SIZE = 64

## Separación horizontal entre columnas de días, en píxeles.
COLUMN_PITCH = 8

## Posición X de la primera columna de días.
GRID_X = 4


class CalendarScene(Scene):
    """
    @brief Escena "Calendario".

    @par Ajustes
    - style: "weeks" (tres semanas alrededor de hoy) o "day" (el día de hoy en grande).
    - color: color de acento (título, día de hoy, fines de semana).
    """

    ## Identificador de la escena.
    name = "calendar"
    ## Nombre visible en la interfaz.
    label = "Calendario"
    ## Ajustes configurables por el usuario.
    settings_schema = {
        "style": {
            "type": "choice",
            "default": "weeks",
            "label": "Estilo",
            "choices": [
                {"value": "weeks", "label": "Semanas"},
                {"value": "day", "label": "Día"},
            ],
        },
        "color": {
            "type": "color",
            "default": "green",
            "label": "Color",
            "choices": [{"value": key, "label": name, "color": hex_color(rgb)} for key, (name, rgb) in COLORS.items()],
        },
    }

    def __init__(self, today: Callable[[], date] = date.today) -> None:
        """
        @brief Crea la escena.
        @param today Función que devuelve la fecha de hoy (se puede sustituir en las pruebas).
        """
        super().__init__()
        ## Función que proporciona la fecha de hoy.
        self._today_fn = today
        ## Fecha de hoy leída en la última llamada a update().
        self._today = today()
        ## Clave del último fotograma dibujado.
        self._cache_key: tuple | None = None
        ## Último fotograma dibujado.
        self._cache_image: Image.Image | None = None

    def on_enter(self) -> None:
        """@brief Al activarse la escena, lee la fecha actual."""
        self._today = self._today_fn()

    def update(self, dt: float) -> None:
        """
        @brief Lee la fecha de hoy (cambia sola a medianoche).
        @param dt Segundos desde el fotograma anterior (no se usa).
        """
        self._today = self._today_fn()

    def render(self, size: int) -> Image.Image:
        """
        @brief Dibuja el calendario, reutilizando el fotograma anterior si no ha cambiado nada.
        @param size Lado del fotograma en píxeles (el diseño es de 64 y se escala si es otro).
        @return Fotograma RGB. Es un objeto compartido con la caché: no hay que modificarlo.
        """
        key = (self.settings["style"], self.settings["color"], self._today, size)
        if key == self._cache_key and self._cache_image is not None:
            return self._cache_image

        render = self._render_day if self.settings["style"] == "day" else self._render_weeks
        frame = render()
        if size != REF_SIZE:
            frame = frame.resize((size, size), Image.Resampling.NEAREST)
        self._cache_key, self._cache_image = key, frame
        return frame

    def _accent(self) -> Color:
        """@brief Color de acento elegido por el usuario."""
        return COLORS[self.settings["color"]][1]

    def _render_weeks(self) -> Image.Image:
        """
        @brief Estilo "Semanas": mes y año, iniciales de los días y tres filas (anterior, actual y siguiente).

        Hoy se marca con un recuadro del color de acento; los fines de semana usan el acento y los días
        de otros meses se ven más apagados. Las columnas alternan de brillo para separar los números.

        @return Fotograma RGB de 64x64.
        """
        today, accent = self._today, self._accent()
        image = Image.new("RGB", (REF_SIZE, REF_SIZE), (0, 0, 0))
        draw = ImageDraw.Draw(image)

        draw_centered(draw, REF_SIZE / 2, 8, f"{MONTHS[today.month - 1]} {today.year}", 1, accent)
        for column, initial in enumerate(DAY_INITIALS):
            draw_text(draw, GRID_X + column * COLUMN_PITCH + 2, 16, initial, 1, dim(accent, 0.55))

        monday = today - timedelta(days=today.weekday())
        for row, week_offset in enumerate((-7, 0, 7)):
            y = 25 + row * 7
            for column in range(7):
                day = monday + timedelta(days=week_offset + column)
                text = str(day.day)
                cell_x = GRID_X + column * COLUMN_PITCH
                if day == today:
                    draw.rectangle((cell_x - 1, y - 1, cell_x + 7, y + 5), fill=accent)
                    color: Color = (0, 0, 0)
                elif day.month != today.month:
                    color = (70, 70, 70) if column % 2 == 0 else (45, 45, 45)
                else:
                    # Las columnas alternan de brillo para que los números de dos cifras no se lean pegados.
                    base = dim(accent, 0.9) if column >= 5 else (215, 215, 215)
                    color = base if column % 2 == 0 else dim(base, 0.6)
                draw_text(draw, cell_x + (7 - text_width(text, 1)) // 2, y, text, 1, color)
        return image

    def _render_day(self) -> Image.Image:
        """
        @brief Estilo "Día": nombre del día, el número en grande y el nombre del mes.
        @return Fotograma RGB de 64x64.
        """
        today, accent = self._today, self._accent()
        image = Image.new("RGB", (REF_SIZE, REF_SIZE), (0, 0, 0))
        draw = ImageDraw.Draw(image)

        draw_centered(draw, REF_SIZE / 2, 11, DAYS_FULL[today.weekday()], 1, dim(accent, 0.8))
        draw_centered(draw, REF_SIZE / 2, 18, str(today.day), 5, accent, spacing=3)
        draw_centered(draw, REF_SIZE / 2, 48, MONTHS_FULL[today.month - 1], 1, dim(accent, 0.8))
        return image
