"""
@file calendar_scene.py
@brief Escena de calendario: la fecha arriba y las notas de ese día ordenadas por hora.

Está pensada para una matriz de 64x64 con una estructura circular delante. Muestra un día: el que se
elige en el calendario de la web (ver NotesStore.view_day en core/notes.py) o, si no se ha elegido
ninguno, el de hoy, que cambia solo a medianoche.

Cada nota pinta su hora con el color elegido para ella en la web (las notas de todo el día, que no
tienen hora, pintan su texto). Si una nota no cabe, su texto se desplaza; si no caben todas las
notas del día, la lista pasa de página sola.

La imagen solo cambia al cambiar de día, de nota o de posición del texto que se desplaza, así que
la CPU apenas trabaja cuando no hay nada que animar.
"""
from __future__ import annotations

import math
import unicodedata
from datetime import date, datetime
from typing import TYPE_CHECKING, Callable

from PIL import Image, ImageDraw

from core.scene import Scene
from scenes.pixeltext import COLORS, DAYS, FONT, MONTHS, Color, dim, draw_text, hex_color, text_width
from scenes.textfonts import TEXT_FONTS, TextFont

if TYPE_CHECKING:
    from core.notes import Note, NotesStore

## Lado (en píxeles) para el que están pensados todos los diseños.
REF_SIZE = 64
## Radio (en píxeles) del círculo visible de la estructura que va delante de la matriz.
CIRCLE_RADIUS = 30.0

## Segundos que se muestra cada página de notas cuando todo cabe.
DWELL = 3.5
## Segundos de pausa al principio y al final de una nota que se desplaza.
PAUSE = 1.5
## Velocidad del desplazamiento, en píxeles por segundo.
SPEED = 12.0
## Color del texto de las notas.
NOTE_COLOR: Color = (235, 235, 235)

## coordenada Y de la fecha de arriba.
DAY_HEADER_Y = 8
## separación vertical entre notas, en píxeles.
DAY_ROW_GAP = 2
## última coordenada Y que puede ocupar la lista (más abajo se corta con el círculo).
DAY_LIST_BOTTOM = 56
## Píxeles entre la hora y el texto de una nota.
DAY_GAP = 2


def _ascii(text: str) -> str:
    """
    @brief Convierte un texto a lo que sabe dibujar la fuente de píxeles: mayúsculas, sin tildes y sin símbolos raros.
    @param text Texto original (puede llevar tildes, ñ, emojis...).
    @return Texto en mayúsculas ASCII, con espacios en lugar de los caracteres no soportados.
    """
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").upper()
    return " ".join("".join(char if char in FONT else " " for char in plain).split())


def _circle_span(top: int, bottom: int) -> tuple[int, int]:
    """
    @brief Parte horizontal de una franja de filas que queda dentro del círculo visible.
    @param top    Primera fila de la franja.
    @param bottom Última fila de la franja.
    @return Tupla (primera columna, última columna) que se ven enteras en toda la franja.
    """
    center = (REF_SIZE - 1) / 2
    dy = max(abs(top - center), abs(bottom - center))
    half = math.sqrt(max(0.0, CIRCLE_RADIUS ** 2 - dy ** 2))
    return math.ceil(center - half) + 1, math.floor(center + half) - 1


def _scroll(overflow: int, local: float) -> int:
    """
    @brief Desplazamiento de un texto que no cabe: pausa, avanza hasta el final y se queda ahí.
    @param overflow Píxeles que sobran.
    @param local    Segundos desde que empezó a mostrarse.
    @return Píxeles a desplazar a la izquierda.
    """
    if overflow <= 0 or local < PAUSE:
        return 0
    return int(min(float(overflow), (local - PAUSE) * SPEED))


def _show_time(overflow: int) -> float:
    """
    @brief Segundos que debe mostrarse un texto para que dé tiempo a leerlo entero.
    @param overflow Píxeles que no caben (0 si cabe).
    @return Segundos.
    """
    return DWELL if overflow <= 0 else 2 * PAUSE + overflow / SPEED


class CalendarScene(Scene):
    """
    @brief Escena "Calendario".

    @par Ajustes
    - color: color de acento (fecha y horas).

    El día que se muestra no es un ajuste de la escena: se guarda con las notas (NotesStore.view_day).
    """

    ## Identificador de la escena.
    name = "calendar"
    ## Nombre visible en la interfaz.
    label = "Calendario"
    ## Ajustes configurables por el usuario.
    settings_schema = {
        "color": {
            "type": "color",
            "default": "green",
            "label": "Color",
            "choices": [{"value": key, "label": name, "color": hex_color(rgb)} for key, (name, rgb) in COLORS.items()],
        },
    }

    def __init__(
        self,
        today: Callable[[], date] = date.today,
        notes: "NotesStore | None" = None,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        """
        @brief Crea la escena.
        @param today Función que devuelve la fecha de hoy (se puede sustituir en las pruebas).
        @param notes Almacén de notas (None si no se usan notas).
        @param now   Función que devuelve la fecha y hora actuales (se puede sustituir en las pruebas).
        """
        super().__init__()
        ## Función que proporciona la fecha de hoy.
        self._today_fn = today
        ## Función que proporciona la hora actual.
        self._now_fn = now
        ## Almacén de notas.
        self._notes = notes
        ## Fecha de hoy leída en la última llamada a update().
        self._today = today()
        ## Minuto actual (hora y minuto) leído en la última llamada a update().
        self._minute = self._now_fn().strftime("%H:%M")
        ## Segundos acumulados desde que se activó la escena (mueve el texto y pasa las páginas).
        self._t = 0.0
        ## Día que se muestra (el elegido en la web, o hoy).
        self._day = self._today
        ## Clave (día mostrado, versión de las notas) de las notas ya leídas.
        self._notes_key: tuple | None = None
        ## Notas del día mostrado (las de todo el día primero y luego por hora).
        self._day_notes: list["Note"] = []
        ## Clave del último fotograma dibujado.
        self._cache_key: tuple | None = None
        ## Último fotograma dibujado.
        self._cache_image: Image.Image | None = None

    def on_enter(self) -> None:
        """@brief Al activarse la escena, lee la fecha actual y reinicia el desplazamiento de las notas."""
        self._today = self._today_fn()
        self._t = 0.0

    def update(self, dt: float) -> None:
        """
        @brief Lee la fecha y la hora, y recalcula las notas si ha cambiado el día o alguna nota.
        @param dt Segundos desde el fotograma anterior (mueve el texto y pasa las páginas).
        """
        self._today = self._today_fn()
        self._t += dt
        self._minute = self._now_fn().strftime("%H:%M")
        chosen = self._notes.view_day() if self._notes is not None else ""
        day = date.fromisoformat(chosen) if chosen else self._today
        version = self._notes.version if self._notes is not None else 0
        key = (day, version)
        if key != self._notes_key:
            if day != self._day:
                self._t = 0.0  # al cambiar de día, la lista empieza por la primera página
            self._day = day
            self._notes_key = key
            self._day_notes = self._notes.on_day(day) if self._notes is not None else []

    def render(self, size: int) -> Image.Image:
        """
        @brief Dibuja el calendario, reutilizando el fotograma anterior si no ha cambiado nada.
        @param size Lado del fotograma en píxeles (el diseño es de 64 y se escala si es otro).
        @return Fotograma RGB. Es un objeto compartido con la caché: no hay que modificarlo.
        """
        font = self._font()
        state = self._day_state(font)
        key = (font.key, self.settings["color"], self._today, self._minute, self._notes_key, state, size)
        if key == self._cache_key and self._cache_image is not None:
            return self._cache_image

        frame = self._render_day(state, font)
        if size != REF_SIZE:
            frame = frame.resize((size, size), Image.Resampling.NEAREST)
        self._cache_key, self._cache_image = key, frame
        return frame

    def _accent(self) -> Color:
        """@brief Color de acento elegido por el usuario."""
        return COLORS[self.settings["color"]][1]

    def _font(self) -> TextFont:
        """@brief Tipografía del texto: siempre la Pequeña (3x5)."""
        return TEXT_FONTS["small"]


    def _is_past(self, note: "Note", day: date) -> bool:
        """
        @brief Indica si una nota de hoy ya ha pasado (tiene hora y esa hora ya ha llegado).
        @param note Nota.
        @param day  Día en el que se muestra.
        @return True si debe verse apagada.
        """
        return day == self._today and bool(note.time) and note.time < self._minute

    # ------------------------------------------------------------------ #
    #  Vista del día
    # ------------------------------------------------------------------ #
    def _day_layout(self, font: TextFont) -> list[tuple[int, int, int]]:
        """
        @brief Posición de cada fila de la lista del estilo "Día".
        @param font Tipografía del texto.
        @return Lista de (Y, primera columna, última columna) de cada fila que cabe.
        """
        top = DAY_HEADER_Y + font.height + 4
        rows = []
        y = top
        while y + font.height - 1 <= DAY_LIST_BOTTOM:
            x0, x1 = _circle_span(y, y + font.height - 1)
            rows.append((y, x0, x1))
            y += font.height + DAY_ROW_GAP
        return rows

    def _day_text_box(self, note: "Note", row: tuple[int, int, int]) -> tuple[int, int]:
        """
        @brief Dónde empieza y cuánto mide el hueco para el texto de una nota en su fila.
        @param note Nota.
        @param row  Fila (Y, primera columna, última columna).
        @return Tupla (X donde empieza el texto, ancho disponible).
        """
        _, x0, x1 = row
        x = x0
        if note.time:
            x += text_width(note.time, 1) + DAY_GAP
        return x, max(1, x1 - x + 1)

    def _day_state(self, font: TextFont) -> tuple:
        """
        @brief Calcula qué página de notas se ve y cuánto está desplazado el texto de cada fila.

        Cada página se muestra hasta que dé tiempo a leer todas sus notas (las que no caben se
        desplazan); después se pasa a la siguiente.

        @param font Tipografía del texto.
        @return Tupla (página, número de páginas, desplazamientos de cada fila).
        """
        notes = self._day_notes
        rows = self._day_layout(font)
        if not notes or not rows:
            return (0, 1, ())
        per_page = len(rows)
        pages = [notes[start:start + per_page] for start in range(0, len(notes), per_page)]
        overflows = []
        for page in pages:
            page_overflow = []
            for note, row in zip(page, rows):
                _, window = self._day_text_box(note, row)
                page_overflow.append(max(0, font.width(_ascii(note.text)) - window))
            overflows.append(page_overflow)
        durations = [max(_show_time(extra) for extra in page) for page in overflows]
        local = self._t % sum(durations)
        index = 0
        while local >= durations[index]:
            local -= durations[index]
            index += 1
        offsets = tuple(_scroll(extra, local) for extra in overflows[index])
        return (index, len(pages), offsets)

    def _render_day(self, state: tuple, font: TextFont) -> Image.Image:
        """
        @brief La fecha arriba y debajo las notas de ese día por horas, con la hora del color de cada nota.

        Las notas de todo el día van primero y sin hora. Las que ya han pasado se ven apagadas. Si
        hay más notas de las que caben, unos puntitos abajo indican en qué página se está.

        @param state Página y desplazamientos calculados por _day_state().
        @param font  Tipografía del texto.
        @return Fotograma RGB de 64x64.
        """
        day, accent = self._day, self._accent()
        image = Image.new("RGB", (REF_SIZE, REF_SIZE), (0, 0, 0))
        draw = ImageDraw.Draw(image)

        header = f"{DAYS[day.weekday()]} {day.day} {MONTHS[day.month - 1]}"
        font.draw(draw, (REF_SIZE - font.width(header)) // 2, DAY_HEADER_Y, header, accent)
        line_y = DAY_HEADER_Y + font.height + 1
        draw.line((20, line_y, REF_SIZE - 21, line_y), fill=dim(accent, 0.25))

        notes = self._day_notes
        rows = self._day_layout(font)
        if not notes:
            empty = "SIN NOTAS"
            font.draw(draw, (REF_SIZE - font.width(empty)) // 2, rows[0][0] + 6 if rows else 30, empty, (70, 70, 70))
            return image

        page, pages, offsets = state
        visible = notes[page * len(rows):(page + 1) * len(rows)]
        for note, row, offset in zip(visible, rows, offsets):
            y, x0, _ = row
            past = self._is_past(note, day)
            note_color = COLORS.get(note.color, COLORS["green"])[1]
            text_color = NOTE_COLOR
            if note.time:
                draw_text(draw, x0, y, note.time, 1, dim(note_color, 0.4) if past else note_color)
            else:
                text_color = note_color  # sin hora, el color de la nota va en el texto
            text_x, window = self._day_text_box(note, row)
            strip = Image.new("RGB", (window, font.height), (0, 0, 0))
            font.draw(ImageDraw.Draw(strip), -offset, 0, _ascii(note.text), dim(text_color, 0.4) if past else text_color)
            image.paste(strip, (text_x, y))

        if pages > 1:
            dots_x = (REF_SIZE - (pages * 3 - 1)) // 2
            for index in range(pages):
                draw.rectangle((dots_x + index * 3, 59, dots_x + index * 3 + 1, 59), fill=accent if index == page else (60, 60, 60))
        return image
