"""
@file textfonts.py
@brief Tipografías de píxeles para texto (letras, números y signos) que se pueden elegir en las escenas.

- **Pequeña** ("small"): la fuente 3x5 de pixeltext.py, de ancho fijo. Es la que más texto deja ver.
- **Fina** ("thin"): 4x6, más legible, con ancho proporcional (la I o el 1 ocupan menos).
- **Alta** ("tall"): 3x7, estrecha y alta. Sale de la Pequeña alargando sus filas intermedias.

Todas dibujan solo mayúsculas sin tildes (ver calendar_scene._ascii); un carácter desconocido se
deja en blanco.
"""
from __future__ import annotations

from dataclasses import dataclass

from PIL import ImageDraw

from scenes.pixeltext import FONT as SMALL_GLYPHS, Color

## Fuente 4x6: carácter -> seis filas de cuatro celdas ("#" encendida, "." apagada) separadas por "/".
_THIN_SOURCE = {
    " ": "..../..../..../..../..../....",
    "A": ".##./#..#/#..#/####/#..#/#..#",
    "B": "###./#..#/###./#..#/#..#/###.",
    "C": ".###/#.../#.../#.../#.../.###",
    "D": "###./#..#/#..#/#..#/#..#/###.",
    "E": "####/#.../###./#.../#.../####",
    "F": "####/#.../###./#.../#.../#...",
    "G": ".###/#.../#.##/#..#/#..#/.###",
    "H": "#..#/#..#/####/#..#/#..#/#..#",
    "I": "###./.#../.#../.#../.#../###.",
    "J": "..##/...#/...#/...#/#..#/.##.",
    "K": "#..#/#.#./##../#.#./#..#/#..#",
    "L": "#.../#.../#.../#.../#.../####",
    "M": "#..#/####/####/#..#/#..#/#..#",
    "N": "#..#/##.#/#.##/#..#/#..#/#..#",
    "O": ".##./#..#/#..#/#..#/#..#/.##.",
    "P": "###./#..#/#..#/###./#.../#...",
    "Q": ".##./#..#/#..#/#..#/#.#./.#.#",
    "R": "###./#..#/#..#/###./#.#./#..#",
    "S": ".###/#.../.##./...#/...#/###.",
    "T": "###./.#../.#../.#../.#../.#..",
    "U": "#..#/#..#/#..#/#..#/#..#/.##.",
    "V": "#..#/#..#/#..#/#..#/.##./.##.",
    "W": "#..#/#..#/#..#/####/####/#..#",
    "X": "#..#/#..#/.##./.##./#..#/#..#",
    "Y": "#.#./#.#./.#../.#../.#../.#..",
    "Z": "####/...#/..#./.#../#.../####",
    "0": ".##./#..#/#.##/##.#/#..#/.##.",
    "1": ".#../##../.#../.#../.#../###.",
    "2": ".##./#..#/..#./.#../#.../####",
    "3": "###./...#/.##./...#/...#/###.",
    "4": "#..#/#..#/####/...#/...#/...#",
    "5": "####/#.../###./...#/...#/###.",
    "6": ".##./#.../###./#..#/#..#/.##.",
    "7": "####/...#/..#./.#../.#../.#..",
    "8": ".##./#..#/.##./#..#/#..#/.##.",
    "9": ".##./#..#/#..#/.###/...#/.##.",
    "-": "..../..../.##./..../..../....",
    "/": "...#/..#./..#./.#../.#../#...",
    ".": "..../..../..../..../..../#...",
    "%": "#..#/...#/..#./.#../#.../#..#",
    "?": ".##./#..#/..#./.#../..../.#..",
    ":": "..../#.../..../..../#.../....",
    ",": "..../..../..../..../.#../#...",
    "!": "#.../#.../#.../#.../..../#...",
    "+": "..../.#../###./.#../..../....",
    "(": ".#../#.../#.../#.../#.../.#..",
    ")": "#.../.#../.#../.#../.#../#...",
    "'": "#.../#.../..../..../..../....",
}

## Filas de la fuente 3x5 que se repiten para obtener la 3x7 (se alargan la 2.ª y la 4.ª).
_TALL_ROWS = (0, 1, 1, 2, 3, 3, 4)


@dataclass(frozen=True)
class TextFont:
    """
    @brief Una tipografía de píxeles: sus dibujos y cómo se mide y se dibuja un texto con ella.
    """

    ## Identificador ("small", "thin" o "tall").
    key: str
    ## Nombre visible en la interfaz.
    label: str
    ## Dibujos: carácter -> tupla de filas.
    glyphs: dict[str, tuple[str, ...]]
    ## Alto de las letras en píxeles.
    height: int
    ## True si cada letra ocupa solo su ancho real; False si todas miden lo mismo.
    proportional: bool
    ## Píxeles de separación entre letras.
    spacing: int = 1

    def _glyph(self, char: str) -> tuple[str, ...]:
        """
        @brief Dibujo de un carácter (en blanco si la fuente no lo tiene).
        @param char Carácter.
        @return Tupla de filas.
        """
        return self.glyphs.get(char, self.glyphs[" "])

    def char_width(self, char: str) -> int:
        """
        @brief Ancho en píxeles de un carácter (sin la separación).
        @param char Carácter.
        @return Ancho en píxeles.
        """
        rows = self._glyph(char)
        if not self.proportional:
            return len(rows[0])
        if char == " ":
            return 2
        used = [index for row in rows for index, cell in enumerate(row) if cell == "#"]
        return max(used) + 1 if used else len(rows[0])

    def width(self, text: str) -> int:
        """
        @brief Ancho en píxeles de un texto.
        @param text Texto a medir.
        @return Ancho total (0 si está vacío).
        """
        if not text:
            return 0
        return sum(self.char_width(char) for char in text) + self.spacing * (len(text) - 1)

    def draw(self, draw: ImageDraw.ImageDraw, x: int, y: int, text: str, fill: Color) -> None:
        """
        @brief Dibuja un texto.
        @param draw Objeto de dibujo.
        @param x    Coordenada X de la esquina superior izquierda.
        @param y    Coordenada Y de la esquina superior izquierda.
        @param text Texto (en mayúsculas).
        @param fill Color RGB.
        """
        for char in text:
            for row_index, row in enumerate(self._glyph(char)):
                for col_index, cell in enumerate(row):
                    if cell == "#":
                        draw.point((x + col_index, y + row_index), fill=fill)
            x += self.char_width(char) + self.spacing


def _parse(source: dict[str, str]) -> dict[str, tuple[str, ...]]:
    """
    @brief Interpreta una fuente escrita como texto ("filas/separadas/por/barras").
    @param source Carácter -> filas separadas por "/".
    @return Carácter -> tupla de filas.
    """
    return {char: tuple(rows.split("/")) for char, rows in source.items()}


## Tipografías disponibles, por identificador.
TEXT_FONTS: dict[str, TextFont] = {
    "small": TextFont("small", "Pequeña", dict(SMALL_GLYPHS), 5, proportional=False),
    "thin": TextFont("thin", "Fina", _parse(_THIN_SOURCE), 6, proportional=True),
    "tall": TextFont(
        "tall", "Alta",
        {char: tuple(rows[index] for index in _TALL_ROWS) for char, rows in SMALL_GLYPHS.items()},
        7, proportional=False,
    ),
}

## Tipografía por defecto.
DEFAULT_TEXT_FONT = "small"


def text_font(key: str) -> TextFont:
    """
    @brief Devuelve una tipografía por su identificador (la Pequeña si no existe).
    @param key Identificador.
    @return Tipografía.
    """
    return TEXT_FONTS.get(key, TEXT_FONTS[DEFAULT_TEXT_FONT])
