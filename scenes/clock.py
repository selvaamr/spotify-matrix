"""
@file clock.py
@brief Escena de reloj: digital o grande, con varias tipografías y colores.

Está pensada para una matriz de 64x64 con una estructura circular delante: todo el contenido
se coloca dentro de un círculo de unos 30 píxeles de radio, para que no se corte por las esquinas.
Los dígitos se dibujan con fuentes de píxeles propias, así que no depende de ninguna fuente
instalada en el sistema.

Siempre se muestra la fecha. No hay segundos: la imagen solo cambia una vez por minuto
(y los dos puntos del reloj digital parpadean), así que la CPU apenas trabaja.

La hora es la del sistema: si en la Raspberry Pi no es la correcta, se arregla con
`sudo timedatectl set-timezone Europe/Madrid`.
"""
from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import Callable

from PIL import Image, ImageDraw

from core.scene import Scene
from scenes.pixeltext import (
    COLORS, DAYS, FONT, MONTHS, Color, dim, draw_text, hex_color, text_width,
)

## Lado (en píxeles) para el que están pensados todos los diseños.
REF_SIZE = 64

## Tipografías de la hora: identificador -> nombre visible.
FONTS = {"block": "Bloque", "round": "Redondeada", "segments": "Segmentos"}

## Segmentos encendidos de cada dígito en la tipografía "Segmentos" (a=arriba, b=arriba dcha., c=abajo dcha.,
## d=abajo, e=abajo izda., f=arriba izda., g=centro).
_SEGMENTS = {
    "0": "abcdef", "1": "bc", "2": "abdeg", "3": "abcdg", "4": "bcfg",
    "5": "acdfg", "6": "acdefg", "7": "abc", "8": "abcdefg", "9": "abcdfg",
}


# --------------------------------------------------------------------------- #
#  Tipografías de la hora
# --------------------------------------------------------------------------- #
def _block_mask(char: str, sx: int, sy: int) -> Image.Image:
    """
    @brief Máscara de un dígito en tipografía de bloques: cada celda de la fuente 3x5 se amplía a sx x sy píxeles.
    @param char Dígito.
    @param sx   Ancho en píxeles de cada celda.
    @param sy   Alto en píxeles de cada celda.
    @return Imagen "L" de (3*sx) x (5*sy) píxeles; 255 donde se dibuja.
    """
    mask = Image.new("L", (3 * sx, 5 * sy), 0)
    draw = ImageDraw.Draw(mask)
    for row_index, row in enumerate(FONT[char]):
        for col_index, cell in enumerate(row):
            if cell == "#":
                x0, y0 = col_index * sx, row_index * sy
                draw.rectangle((x0, y0, x0 + sx - 1, y0 + sy - 1), fill=255)
    return mask


def _chamfer(mask: Image.Image, passes: int = 1) -> Image.Image:
    """
    @brief Redondea las esquinas exteriores de una máscara quitando los píxeles que sobresalen en ángulo recto.
    @param mask   Máscara "L" (se modifica y se devuelve).
    @param passes Cuántas veces se repite el recorte (más pasadas = esquinas más redondeadas).
    @return La misma máscara, ya redondeada.
    """
    width, height = mask.size
    for _ in range(passes):
        pixels = mask.load()
        corners = []
        for y in range(height):
            for x in range(width):
                if not pixels[x, y]:
                    continue
                up = y > 0 and pixels[x, y - 1]
                down = y < height - 1 and pixels[x, y + 1]
                left = x > 0 and pixels[x - 1, y]
                right = x < width - 1 and pixels[x + 1, y]
                if (not up and not left) or (not up and not right) or (not down and not left) or (not down and not right):
                    corners.append((x, y))
        for x, y in corners:
            pixels[x, y] = 0
    return mask


def _segments_mask(segments: str, width: int, height: int, thickness: int = 2) -> Image.Image:
    """
    @brief Máscara de un dígito de siete segmentos (estilo pantalla LED/LCD).
    @param segments  Letras de los segmentos encendidos (ver _SEGMENTS).
    @param width     Ancho del dígito en píxeles.
    @param height    Alto del dígito en píxeles.
    @param thickness Grosor de los segmentos en píxeles.
    @return Imagen "L" de width x height píxeles.
    """
    t = thickness
    mid0 = (height - t) // 2
    mid1 = mid0 + t - 1
    rects = {
        "a": (t, 0, width - 1 - t, t - 1),
        "g": (t, mid0, width - 1 - t, mid1),
        "d": (t, height - t, width - 1 - t, height - 1),
        "f": (0, t, t - 1, mid1),
        "e": (0, mid0, t - 1, height - t - 1),
        "b": (width - t, t, width - 1, mid1),
        "c": (width - t, mid0, width - 1, height - t - 1),
    }
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    for segment in segments:
        draw.rectangle(rects[segment], fill=255)
    return mask


@lru_cache(maxsize=None)
def _digit_mask(font: str, char: str, sx: int, sy: int) -> Image.Image | None:
    """
    @brief Devuelve (con caché) la máscara de un dígito en la tipografía indicada.
    @param font Identificador de tipografía (ver FONTS).
    @param char Dígito, " " (hueco) o "8" para obtener todos los segmentos.
    @param sx   Ancho en píxeles de cada celda de la rejilla 3x5.
    @param sy   Alto en píxeles de cada celda.
    @return Máscara "L" de (3*sx) x (5*sy) píxeles, o None si es un hueco. No debe modificarse.
    """
    if char == " ":
        return None
    if font == "segments":
        return _segments_mask(_SEGMENTS[char], 3 * sx, 5 * sy)
    mask = _block_mask(char, sx, sy)
    return _chamfer(mask, 1) if font == "round" else mask


def _draw_digit(image: Image.Image, font: str, char: str, x: int, y: int, sx: int, sy: int, color: Color) -> None:
    """
    @brief Dibuja un dígito de la hora. En la tipografía "Segmentos" los segmentos apagados se ven muy tenues.
    @param image Imagen RGB sobre la que se dibuja.
    @param font  Identificador de tipografía.
    @param char  Dígito a dibujar.
    @param x     Coordenada X de la esquina superior izquierda.
    @param y     Coordenada Y de la esquina superior izquierda.
    @param sx    Ancho en píxeles de cada celda de la rejilla 3x5.
    @param sy    Alto en píxeles de cada celda.
    @param color Color RGB.
    """
    mask = _digit_mask(font, char, sx, sy)
    if mask is None:
        return
    if font == "segments":
        image.paste(dim(color, 0.10), (x, y), _digit_mask(font, "8", sx, sy))
    image.paste(color, (x, y), mask)


def _draw_colon(image: Image.Image, font: str, x: int, y: int, height: int, color: Color) -> None:
    """
    @brief Dibuja los dos puntos que separan horas y minutos, con el estilo de la tipografía.
    @param image  Imagen RGB sobre la que se dibuja.
    @param font   Identificador de tipografía.
    @param x      Coordenada X del hueco de 4 píxeles reservado para los dos puntos.
    @param y      Coordenada Y de la parte superior de los dígitos.
    @param height Alto de los dígitos en píxeles.
    @param color  Color RGB.
    """
    size = 4 if font in ("block", "round") else 2
    dot = Image.new("L", (size, size), 255)
    if font == "round":
        _chamfer(dot, 1)
    for ratio in (0.32, 0.68):
        top = y + round(height * ratio) - size // 2
        image.paste(color, (x + (4 - size) // 2, top), dot)


class ClockScene(Scene):
    """
    @brief Escena "Reloj".

    @par Ajustes
    - style: digital (HH:MM y fecha) o grande (horas sobre minutos y fecha).
    - font: tipografía de la hora (bloque, redondeada o segmentos).
    - color: color de los dígitos.
    - hour_format: 24 o 12 horas (con AM/PM).
    """

    ## Identificador de la escena.
    name = "clock"
    ## Nombre visible en la interfaz.
    label = "Reloj"
    ## Ajustes configurables por el usuario.
    settings_schema = {
        "style": {
            "type": "choice",
            "default": "digital",
            "label": "Estilo",
            "choices": [
                {"value": "digital", "label": "Digital"},
                {"value": "stacked", "label": "Grande"},
            ],
        },
        "font": {
            "type": "choice",
            "default": "block",
            "label": "Tipografía",
            "choices": [{"value": key, "label": name} for key, name in FONTS.items()],
        },
        "color": {
            "type": "color",
            "default": "green",
            "label": "Color",
            "choices": [{"value": key, "label": name, "color": hex_color(rgb)} for key, (name, rgb) in COLORS.items()],
        },
        "hour_format": {
            "type": "choice",
            "default": "24h",
            "label": "Formato de hora",
            "choices": [{"value": "24h", "label": "24 horas"}, {"value": "12h", "label": "12 horas"}],
        },
    }

    def __init__(self, clock: Callable[[], datetime] = datetime.now) -> None:
        """
        @brief Crea la escena.
        @param clock Función que devuelve la fecha y hora actuales (se puede sustituir en las pruebas).
        """
        super().__init__()
        ## Función que proporciona la hora.
        self._clock = clock
        ## Hora leída en la última llamada a update().
        self._now = clock()
        ## Clave del último fotograma dibujado (si no cambia, se reutiliza la imagen).
        self._cache_key: tuple | None = None
        ## Último fotograma dibujado.
        self._cache_image: Image.Image | None = None

    def on_enter(self) -> None:
        """@brief Al activarse la escena, lee la hora actual."""
        self._now = self._clock()

    def update(self, dt: float) -> None:
        """
        @brief Lee la hora actual.
        @param dt Segundos desde el fotograma anterior (no se usa).
        """
        self._now = self._clock()

    def render(self, size: int) -> Image.Image:
        """
        @brief Dibuja la hora, reutilizando el fotograma anterior si no ha cambiado nada visible.
        @param size Lado del fotograma en píxeles (el diseño es de 64 y se escala si es otro).
        @return Fotograma RGB. Es un objeto compartido con la caché: no hay que modificarlo.
        """
        key = self._frame_key(size)
        if key == self._cache_key and self._cache_image is not None:
            return self._cache_image

        render = self._render_stacked if self.settings["style"] == "stacked" else self._render_digital
        frame = render()
        if size != REF_SIZE:
            frame = frame.resize((size, size), Image.Resampling.NEAREST)

        self._cache_key, self._cache_image = key, frame
        return frame

    def _frame_key(self, size: int) -> tuple:
        """
        @brief Calcula una clave que identifica todo lo que influye en el aspecto del fotograma.

        Dos fotogramas con la misma clave se ven exactamente igual.

        @param size Lado del fotograma en píxeles.
        @return Tupla comparable.
        """
        s, now = self.settings, self._now
        colon = self._colon_visible() if s["style"] == "digital" else None
        return (
            s["style"], size, s["color"], s["font"], s["hour_format"],
            now.hour, now.minute, (now.weekday(), now.day, now.month), colon,
        )

    def _colon_visible(self) -> bool:
        """@brief Los dos puntos del reloj digital se ven durante la primera mitad de cada segundo."""
        return self._now.microsecond < 500_000

    def _color(self) -> Color:
        """@brief Color RGB elegido por el usuario."""
        return COLORS[self.settings["color"]][1]

    def _font(self) -> str:
        """@brief Tipografía elegida (con "block" si el ajuste no fuese válido)."""
        font = self.settings["font"]
        return font if font in FONTS else "block"

    def _hour_text(self) -> tuple[str, str]:
        """
        @brief Prepara el texto de la hora según el formato elegido.
        @return Tupla (horas en dos caracteres, "AM"/"PM" o cadena vacía en el formato de 24 horas).
        """
        hour = self._now.hour
        if self.settings["hour_format"] == "12h":
            return f"{hour % 12 or 12:2d}", "AM" if hour < 12 else "PM"
        return f"{hour:02d}", ""

    def _date_line(self, ampm: str = "") -> str:
        """
        @brief Texto de la línea de fecha, por ejemplo "VIE 30 OCT" (más "PM" si se indica).
        @param ampm "AM", "PM" o cadena vacía.
        @return Texto de la línea.
        """
        now = self._now
        line = f"{DAYS[now.weekday()]} {now.day} {MONTHS[now.month - 1]}"
        return f"{line} {ampm}" if ampm else line

    def _render_digital(self) -> Image.Image:
        """
        @brief Estilo digital: HH:MM con la tipografía elegida y, debajo, la fecha.

        Cada dígito mide 9x20 píxeles y el conjunto ocupa 50 de ancho, para que quepa dentro del círculo.

        @return Fotograma RGB de 64x64.
        """
        color, font = self._color(), self._font()
        hours, ampm = self._hour_text()
        sx, sy = 3, 4
        height, gap, line_height = 5 * sy, 6, 5
        y = (REF_SIZE - (height + gap + line_height)) // 2

        image = Image.new("RGB", (REF_SIZE, REF_SIZE), (0, 0, 0))
        x0 = 7
        if hours.startswith(" "):
            # Hora de una cifra (12h): se descarta el hueco de la izquierda y se centra el conjunto.
            x0 = 2
        else:
            _draw_digit(image, font, hours[0], x0, y, sx, sy, color)
        _draw_digit(image, font, hours[1], x0 + 11, y, sx, sy, color)
        minutes = f"{self._now.minute:02d}"
        _draw_digit(image, font, minutes[0], x0 + 30, y, sx, sy, color)
        _draw_digit(image, font, minutes[1], x0 + 41, y, sx, sy, color)
        if self._colon_visible():
            _draw_colon(image, font, x0 + 23, y, height, color)

        draw = ImageDraw.Draw(image)
        line = self._date_line(ampm)
        draw_text(draw, (REF_SIZE - text_width(line, 1)) // 2, y + height + gap, line, 1, dim(color, 0.7))
        return image

    def _render_stacked(self) -> Image.Image:
        """
        @brief Estilo grande: las horas sobre los minutos y, debajo, la fecha.

        Cada dígito mide 12x15 píxeles. En el formato de 12 horas, AM/PM va a la derecha, entre las dos filas.

        @return Fotograma RGB de 64x64.
        """
        color, font = self._color(), self._font()
        hours, ampm = self._hour_text()
        sx, sy = 4, 3
        row, y, x0 = 5 * sy, 10, 18

        image = Image.new("RGB", (REF_SIZE, REF_SIZE), (0, 0, 0))
        if hours.startswith(" "):
            # Hora de una cifra (12h): se centra sobre los minutos en vez de dejar un hueco a la izquierda.
            _draw_digit(image, font, hours[1], x0 + 8, y, sx, sy, color)
        else:
            _draw_digit(image, font, hours[0], x0, y, sx, sy, color)
            _draw_digit(image, font, hours[1], x0 + 15, y, sx, sy, color)
        minutes = f"{self._now.minute:02d}"
        _draw_digit(image, font, minutes[0], x0, y + row + 3, sx, sy, color)
        _draw_digit(image, font, minutes[1], x0 + 15, y + row + 3, sx, sy, color)

        draw = ImageDraw.Draw(image)
        if ampm:
            draw_text(draw, x0 + 30, y + row - 2, ampm, 1, dim(color, 0.7))
        line = self._date_line()
        draw_text(draw, (REF_SIZE - text_width(line, 1)) // 2, y + 2 * row + 3 + 5, line, 1, dim(color, 0.7))
        return image