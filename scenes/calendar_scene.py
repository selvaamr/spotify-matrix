"""
@file calendar_scene.py
@brief Escena de calendario con dos estilos: el día en grande, o la agenda de 3 días con notas.

Está pensada para una matriz de 64x64 con una estructura circular delante. El estilo "Día" muestra
la fecha de hoy a lo grande, y el estilo "3 días" muestra hoy, mañana y pasado con las notas de cada
día (ver core/notes.py).

La imagen solo cambia al cambiar de día, de nota o de posición del texto que se desplaza, así que
la CPU apenas trabaja cuando no hay nada que animar.
"""
from __future__ import annotations

import unicodedata
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Callable

from PIL import Image, ImageDraw

from core.scene import Scene
from scenes.pixeltext import (
    COLORS, DAYS, DAYS_FULL, FONT, MONTHS_FULL, Color, dim, draw_centered, draw_text, hex_color, text_width,
)

if TYPE_CHECKING:
    from core.notes import Note, NotesStore

## Lado (en píxeles) para el que están pensados todos los diseños.
REF_SIZE = 64

## Filas de la agenda: coordenada Y de la línea del título (la del texto de la nota va 6 píxeles más abajo).
AGENDA_ROWS = (12, 27, 42)
## Coordenada X donde empieza el texto de la agenda.
AGENDA_X = 12
## Ancho útil de la línea del título (día y hora) de cada fila, para no salirse del círculo.
AGENDA_TITLE_WIDTH = (42, 48, 46)
## Ancho útil de la línea de la nota de cada fila.
AGENDA_TEXT_WIDTH = (46, 48, 42)
## Máximo de puntos que indican cuántas notas hay en un día.
AGENDA_MAX_DOTS = 4
## Segundos que se muestra cada nota cuando cabe entera.
AGENDA_DWELL = 3.5
## Segundos de pausa al principio y al final de una nota que se desplaza.
AGENDA_PAUSE = 1.5
## Velocidad del desplazamiento, en píxeles por segundo.
AGENDA_SPEED = 12.0
## Color del texto de las notas.
NOTE_COLOR: Color = (235, 235, 235)


def _ascii(text: str) -> str:
    """
    @brief Convierte un texto a lo que sabe dibujar la fuente de píxeles: mayúsculas, sin tildes y sin símbolos raros.
    @param text Texto original (puede llevar tildes, ñ, emojis...).
    @return Texto en mayúsculas ASCII, con espacios en lugar de los caracteres no soportados.
    """
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").upper()
    return " ".join("".join(char if char in FONT else " " for char in plain).split())


class CalendarScene(Scene):
    """
    @brief Escena "Calendario".

    @par Ajustes
    - style: "day" (el día de hoy en grande) o "agenda" (hoy, mañana y pasado con sus notas).
    - color: color de acento (día de hoy, horas).
    """

    ## Identificador de la escena.
    name = "calendar"
    ## Nombre visible en la interfaz.
    label = "Calendario"
    ## Ajustes configurables por el usuario.
    settings_schema = {
        "style": {
            "type": "choice",
            "default": "day",
            "label": "Estilo",
            "choices": [
                {"value": "day", "label": "Día"},
                {"value": "agenda", "label": "3 días"},
            ],
        },
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
        @param notes Almacén de notas para el estilo "3 días" (None si no se usan notas).
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
        ## Segundos acumulados desde que se activó la escena (mueve el texto de la agenda).
        self._t = 0.0
        ## Clave (día, versión de las notas) de la agenda ya calculada.
        self._agenda_key: tuple | None = None
        ## Filas de la agenda: (etiqueta, día, notas) para hoy, mañana y pasado.
        self._agenda: list[tuple[str, date, list["Note"]]] = []
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
        @brief Lee la fecha y la hora (cambian solas) y, en el estilo "3 días", recalcula las notas si hace falta.
        @param dt Segundos desde el fotograma anterior (mueve el texto de la agenda).
        """
        self._today = self._today_fn()
        if self.settings["style"] != "agenda":
            return
        self._t += dt
        self._minute = self._now_fn().strftime("%H:%M")
        version = self._notes.version if self._notes is not None else 0
        key = (self._today, version)
        if key != self._agenda_key:
            self._agenda_key = key
            self._agenda = []
            for offset in range(3):
                day = self._today + timedelta(days=offset)
                label = "HOY" if offset == 0 else "MANANA" if offset == 1 else f"{DAYS[day.weekday()]} {day.day}"
                self._agenda.append((label, day, self._notes.on_day(day) if self._notes is not None else []))

    def render(self, size: int) -> Image.Image:
        """
        @brief Dibuja el calendario, reutilizando el fotograma anterior si no ha cambiado nada.
        @param size Lado del fotograma en píxeles (el diseño es de 64 y se escala si es otro).
        @return Fotograma RGB. Es un objeto compartido con la caché: no hay que modificarlo.
        """
        style = self.settings["style"]
        states: tuple = ()
        if style == "agenda":
            states = self._agenda_states()
            key = (style, self.settings["color"], self._today, self._minute, self._agenda_key, states, size)
        else:
            key = (style, self.settings["color"], self._today, size)
        if key == self._cache_key and self._cache_image is not None:
            return self._cache_image

        if style == "agenda":
            frame = self._render_agenda(states)
        else:
            frame = self._render_day()
        if size != REF_SIZE:
            frame = frame.resize((size, size), Image.Resampling.NEAREST)
        self._cache_key, self._cache_image = key, frame
        return frame

    def _accent(self) -> Color:
        """@brief Color de acento elegido por el usuario."""
        return COLORS[self.settings["color"]][1]

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

    def _agenda_states(self) -> tuple:
        """
        @brief Calcula qué nota se muestra en cada fila de la agenda y cuánto está desplazado su texto.

        Cada nota se muestra unos segundos; si no cabe en el ancho disponible, hace una pausa, se
        desplaza hasta el final, hace otra pausa y pasa a la siguiente.

        @return Tupla con (índice de la nota, desplazamiento en píxeles) para cada fila.
        """
        states = []
        for row, (_, _, notes) in enumerate(self._agenda):
            if not notes:
                states.append((0, 0))
                continue
            window = AGENDA_TEXT_WIDTH[row]
            overflow = [max(0, text_width(_ascii(note.text), 1) - window) for note in notes]
            durations = [AGENDA_DWELL if extra == 0 else 2 * AGENDA_PAUSE + extra / AGENDA_SPEED for extra in overflow]
            local = self._t % sum(durations)
            index = 0
            while local >= durations[index]:
                local -= durations[index]
                index += 1
            extra = overflow[index]
            if extra == 0 or local < AGENDA_PAUSE:
                offset = 0.0
            else:
                offset = min(float(extra), (local - AGENDA_PAUSE) * AGENDA_SPEED)
            states.append((index, int(offset)))
        return tuple(states)

    def _render_agenda(self, states: tuple) -> Image.Image:
        """
        @brief Estilo "3 días": tres filas (hoy, mañana y pasado) con el día, la hora y el texto de la nota.

        Cada fila lleva en una línea el día (y a su derecha la hora de la nota), y debajo el texto de la
        nota. Si el día tiene varias notas se van turnando y unas rayitas indican cuántas hay (la activa, resaltada). Las notas
        de hoy cuya hora ya ha pasado se ven apagadas.

        @param states Posición (nota, desplazamiento) de cada fila, calculada por _agenda_states().
        @return Fotograma RGB de 64x64.
        """
        accent = self._accent()
        image = Image.new("RGB", (REF_SIZE, REF_SIZE), (0, 0, 0))
        draw = ImageDraw.Draw(image)

        for divider in (24, 39):
            draw.line((AGENDA_X + 6, divider, AGENDA_X + 34, divider), fill=(32, 32, 32))

        for row, ((label, day, notes), (index, offset)) in enumerate(zip(self._agenda, states)):
            y = AGENDA_ROWS[row]
            draw_text(draw, AGENDA_X, y, label, 1, accent if row == 0 else (170, 170, 170))
            if not notes:
                draw_text(draw, AGENDA_X, y + 6, "SIN NOTAS", 1, (70, 70, 70))
                continue

            note = notes[index]
            past = day == self._today and bool(note.time) and note.time < self._minute
            text_color = dim(NOTE_COLOR, 0.4) if past else NOTE_COLOR

            title_end = AGENDA_X + AGENDA_TITLE_WIDTH[row]
            time_x = title_end
            if note.time:
                time_x = title_end - text_width(note.time, 1)
                draw_text(draw, time_x, y, note.time, 1, dim(accent, 0.45) if past else accent)

            dots = min(len(notes), AGENDA_MAX_DOTS)
            if dots > 1:
                dots_width = dots * 2 - 1
                dots_x = AGENDA_X + text_width(label, 1) + 3
                if dots_x + dots_width + 2 <= time_x:
                    for dot in range(dots):
                        draw.line((dots_x + dot * 2, y + 1, dots_x + dot * 2, y + 3), fill=accent if dot == index else (70, 70, 70))

            window = AGENDA_TEXT_WIDTH[row]
            text = _ascii(note.text)
            strip = Image.new("RGB", (window, 5), (0, 0, 0))
            draw_text(ImageDraw.Draw(strip), -offset, 0, text, 1, text_color)
            image.paste(strip, (AGENDA_X, y + 6))
        return image
