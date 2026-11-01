"""
@file pixeltext.py
@brief Texto con fuente de píxeles 3x5 y datos comunes (colores, días y meses) para las escenas.

Así el reloj, el calendario y el tiempo comparten la misma tipografía pequeña y no dependen de
ninguna fuente instalada en el sistema.
"""
from __future__ import annotations

from PIL import ImageDraw

## Color RGB.
Color = tuple[int, int, int]

## Colores disponibles para el usuario: identificador -> (nombre, color RGB). El nombre solo se usa como texto accesible en la web.
COLORS: dict[str, tuple[str, Color]] = {
    "green": ("Verde", (30, 215, 96)),
    "white": ("Blanco", (235, 235, 235)),
    "cyan": ("Cian", (0, 200, 255)),
    "blue": ("Azul", (70, 110, 255)),
    "violet": ("Violeta", (170, 90, 255)),
    "magenta": ("Magenta", (255, 60, 200)),
    "red": ("Rojo", (255, 50, 50)),
    "amber": ("Ámbar", (255, 170, 0)),
}

## Abreviaturas de los días de la semana (el lunes es el índice 0, como en datetime.weekday()).
DAYS = ("LUN", "MAR", "MIE", "JUE", "VIE", "SAB", "DOM")

## Nombres completos de los días de la semana (sin tildes, porque la fuente no las tiene).
DAYS_FULL = ("LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO", "DOMINGO")

## Iniciales de los días de la semana, empezando en lunes.
DAY_INITIALS = ("L", "M", "X", "J", "V", "S", "D")

## Abreviaturas de los meses.
MONTHS = ("ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC")

## Nombres completos de los meses.
MONTHS_FULL = (
    "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
    "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE",
)

## Fuente de píxeles 3x5: carácter -> cinco filas de tres celdas ("#" encendida, "." apagada) separadas por "/".
_FONT_SOURCE = {
    " ": ".../.../.../.../...",
    "0": "###/#.#/#.#/#.#/###",
    "1": ".#./##./.#./.#./###",
    "2": "###/..#/###/#../###",
    "3": "###/..#/###/..#/###",
    "4": "#.#/#.#/###/..#/..#",
    "5": "###/#../###/..#/###",
    "6": "###/#../###/#.#/###",
    "7": "###/..#/.#./.#./.#.",
    "8": "###/#.#/###/#.#/###",
    "9": "###/#.#/###/..#/###",
    "A": ".#./#.#/###/#.#/#.#",
    "B": "##./#.#/##./#.#/##.",
    "C": ".##/#../#../#../.##",
    "D": "##./#.#/#.#/#.#/##.",
    "E": "###/#../##./#../###",
    "F": "###/#../##./#../#..",
    "G": ".##/#../#.#/#.#/.##",
    "H": "#.#/#.#/###/#.#/#.#",
    "I": "###/.#./.#./.#./###",
    "J": "..#/..#/..#/#.#/.#.",
    "K": "#.#/#.#/##./#.#/#.#",
    "L": "#../#../#../#../###",
    "M": "#.#/###/###/#.#/#.#",
    "N": "##./#.#/#.#/#.#/#.#",
    "O": "###/#.#/#.#/#.#/###",
    "P": "###/#.#/###/#../#..",
    "R": "##./#.#/##./#.#/#.#",
    "S": ".##/#../.#./..#/##.",
    "T": "###/.#./.#./.#./.#.",
    "U": "#.#/#.#/#.#/#.#/###",
    "V": "#.#/#.#/#.#/#.#/.#.",
    "X": "#.#/#.#/.#./#.#/#.#",
    "Y": "#.#/#.#/.#./.#./.#.",
    "Z": "###/..#/.#./#../###",
    "-": ".../.../###/.../...",
    "/": "..#/..#/.#./#../#..",
    ".": ".../.../.../.../.#.",
    "%": "#.#/..#/.#./#../#.#",
    "?": "###/..#/.##/.../.#.",
}

## Fuente ya interpretada: carácter -> tupla de cinco filas.
FONT = {char: tuple(rows.split("/")) for char, rows in _FONT_SOURCE.items()}


def text_width(text: str, scale: int, spacing: int = 1) -> int:
    """
    @brief Calcula el ancho en píxeles de un texto dibujado con la fuente de píxeles 3x5.
    @param text    Texto a medir.
    @param scale   Ampliación de la fuente (1 = letras de 3x5 píxeles).
    @param spacing Píxeles de separación entre caracteres.
    @return Ancho total en píxeles (0 si el texto está vacío).
    """
    return len(text) * (3 * scale + spacing) - spacing if text else 0


def draw_text(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    text: str,
    scale: int,
    fill: Color,
    spacing: int = 1,
) -> None:
    """
    @brief Dibuja un texto con la fuente de píxeles 3x5. Los caracteres desconocidos se dejan en blanco.
    @param draw    Objeto de dibujo.
    @param x       Coordenada X de la esquina superior izquierda.
    @param y       Coordenada Y de la esquina superior izquierda.
    @param text    Texto a dibujar (en mayúsculas).
    @param scale   Ampliación de la fuente (cada celda mide scale x scale píxeles).
    @param fill    Color RGB.
    @param spacing Píxeles de separación entre caracteres.
    """
    for char in text:
        for row_index, row in enumerate(FONT.get(char, FONT[" "])):
            for col_index, cell in enumerate(row):
                if cell == "#":
                    x0, y0 = x + col_index * scale, y + row_index * scale
                    draw.rectangle((x0, y0, x0 + scale - 1, y0 + scale - 1), fill=fill)
        x += 3 * scale + spacing


def draw_centered(draw: ImageDraw.ImageDraw, cx: float, y: int, text: str, scale: int, fill: Color, spacing: int = 1) -> None:
    """
    @brief Dibuja un texto centrado horizontalmente alrededor de una coordenada.
    @param draw    Objeto de dibujo.
    @param cx      Coordenada X del centro.
    @param y       Coordenada Y de la parte superior.
    @param text    Texto a dibujar.
    @param scale   Ampliación de la fuente.
    @param fill    Color RGB.
    @param spacing Separación entre caracteres.
    """
    draw_text(draw, int(round(cx - text_width(text, scale, spacing) / 2)), y, text, scale, fill, spacing)


def dim(color: Color, factor: float) -> Color:
    """
    @brief Oscurece un color multiplicando sus canales.
    @param color  Color RGB original.
    @param factor Multiplicador (entre 0 y 1 oscurece).
    @return Color RGB resultante.
    """
    return tuple(int(channel * factor) for channel in color)  # type: ignore[return-value]


def hex_color(color: Color) -> str:
    """
    @brief Convierte un color RGB a texto hexadecimal para la web.
    @param color Color RGB.
    @return Texto con el formato "#rrggbb".
    """
    return "#{:02x}{:02x}{:02x}".format(*color)
