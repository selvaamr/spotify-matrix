"""
@file weather.py
@brief Escena del tiempo: temperatura actual con icono, o previsión de tres días.

Los datos los descarga services.weather.WeatherPoller en segundo plano; esta escena solo los
dibuja. Los iconos se dibujan ampliados (supersampling) y se reducen, para que salgan suaves.
Todo el contenido queda dentro de un círculo de unos 30 píxeles de radio, para la estructura
circular que enmarca la matriz.
"""
from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw

from core.scene import Scene
from scenes.pixeltext import DAYS, Color, dim, draw_centered, draw_text, text_width

if TYPE_CHECKING:
    from services.weather import DayForecast, WeatherData, WeatherPoller

## Lado (en píxeles) para el que están pensados todos los diseños.
REF_SIZE = 64

## Factor de supersampling de los iconos.
SS = 8

## Tamaño del lienzo en el que se diseñan los iconos (se escalan al tamaño pedido).
ICON_W, ICON_H = 32, 24

## Color del texto secundario.
GRAY: Color = (150, 150, 150)
## Color de las temperaturas mínimas.
COLD: Color = (90, 160, 255)
## Color de las temperaturas máximas.
HOT: Color = (255, 150, 50)


def icon_kind(code: int) -> str:
    """
    @brief Traduce un código meteorológico WMO al tipo de icono.
    @param code Código WMO (0 despejado ... 99 tormenta con granizo).
    @return "clear", "partly", "overcast", "fog", "drizzle", "rain", "snow" o "storm".
    """
    if code == 0 or code == 1:
        return "clear"
    if code == 2:
        return "partly"
    if code in (45, 48):
        return "fog"
    if code in (51, 53, 55, 56, 57):
        return "drizzle"
    if code in (61, 63, 65, 66, 67, 80, 81, 82):
        return "rain"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    if code in (95, 96, 99):
        return "storm"
    return "overcast"


# --------------------------------------------------------------------------- #
#  Iconos
# --------------------------------------------------------------------------- #
def _ellipse(d: ImageDraw.ImageDraw, cx: float, cy: float, r: float, fill: Color) -> None:
    """@brief Dibuja un círculo en coordenadas del lienzo de 32x24."""
    d.ellipse(((cx - r) * SS, (cy - r) * SS, (cx + r) * SS, (cy + r) * SS), fill=fill)


def _line(d: ImageDraw.ImageDraw, a: tuple[float, float], b: tuple[float, float], width: float, fill: Color) -> None:
    """@brief Dibuja una línea con extremos redondeados en coordenadas del lienzo de 32x24."""
    d.line((a[0] * SS, a[1] * SS, b[0] * SS, b[1] * SS), fill=fill, width=max(1, int(width * SS)))
    for x, y in (a, b):
        _ellipse(d, x, y, width / 2, fill)


def _cloud(d: ImageDraw.ImageDraw, color: Color, dx: float = 0.0, dy: float = 0.0, scale: float = 1.0, pad: float = 0.0) -> None:
    """
    @brief Dibuja una nube (una píldora con dos bultos) en coordenadas del lienzo de 32x24.
    @param d     Objeto de dibujo.
    @param color Color de la nube.
    @param dx    Desplazamiento horizontal.
    @param dy    Desplazamiento vertical.
    @param scale Escala respecto al centro de la nube.
    @param pad   Margen extra que engorda la nube (sirve para dibujar un hueco negro alrededor).
    """
    def pt(x: float, y: float) -> tuple[float, float]:
        return 16 + (x - 16) * scale + dx, 12 + (y - 12) * scale + dy

    x0, y0 = pt(5, 13)
    x1, y1 = pt(28, 21)
    d.rounded_rectangle(((x0 - pad) * SS, (y0 - pad) * SS, (x1 + pad) * SS, (y1 + pad) * SS), radius=(4 * scale + pad) * SS, fill=color)
    for cx, cy, r in ((12, 12.5, 5), (19.5, 10, 6.5)):
        px, py = pt(cx, cy)
        _ellipse(d, px, py, r * scale + pad, color)


def _sun(d: ImageDraw.ImageDraw, cx: float, cy: float, r: float, rays: tuple[float, float], width: float) -> None:
    """
    @brief Dibuja un sol con ocho rayos.
    @param d     Objeto de dibujo.
    @param cx    Centro X.
    @param cy    Centro Y.
    @param r     Radio del disco.
    @param rays  Distancia interior y exterior de los rayos al centro.
    @param width Grosor de los rayos.
    """
    import math

    color = (255, 200, 40)
    for index in range(8):
        a = math.radians(index * 45)
        _line(d, (cx + rays[0] * math.sin(a), cy - rays[0] * math.cos(a)), (cx + rays[1] * math.sin(a), cy - rays[1] * math.cos(a)), width, color)
    _ellipse(d, cx, cy, r, color)


def _moon(d: ImageDraw.ImageDraw, cx: float, cy: float, r: float) -> None:
    """@brief Dibuja una luna creciente (un disco al que se le recorta otro desplazado)."""
    _ellipse(d, cx, cy, r, (235, 235, 205))
    _ellipse(d, cx + r * 0.6, cy - r * 0.4, r * 0.85, (0, 0, 0))


@lru_cache(maxsize=64)
def make_icon(kind: str, is_day: bool, width: int, height: int) -> Image.Image:
    """
    @brief Dibuja (con caché) el icono del tiempo.
    @param kind   Tipo de icono (ver icon_kind).
    @param is_day True si es de día (cambia el sol por la luna).
    @param width  Ancho final en píxeles.
    @param height Alto final en píxeles.
    @return Imagen RGB con fondo negro. No debe modificarse.
    """
    image = Image.new("RGB", (ICON_W * SS, ICON_H * SS), (0, 0, 0))
    d = ImageDraw.Draw(image)
    light, grey, dark = (225, 230, 240), (170, 180, 200), (105, 110, 135)

    if kind == "clear":
        if is_day:
            _sun(d, 16, 12, 5.5, (8.3, 11.3), 1.8)
        else:
            _moon(d, 16, 12, 8)
    elif kind == "partly":
        if is_day:
            _sun(d, 11, 9, 4.2, (6.6, 9.2), 1.4)
        else:
            _moon(d, 11, 9, 5.5)
        _cloud(d, (0, 0, 0), dx=3, dy=3, scale=0.85, pad=1.2)
        _cloud(d, light, dx=3, dy=3, scale=0.85)
    elif kind == "overcast":
        _cloud(d, (130, 135, 155), dx=-4, dy=-3, scale=0.8)
        _cloud(d, (0, 0, 0), dx=2, dy=1, scale=0.9, pad=1.2)
        _cloud(d, light, dx=2, dy=1, scale=0.9)
    elif kind == "fog":
        for (x0, x1, y) in ((5, 27, 7), (3, 24, 12.5), (8, 29, 18)):
            _line(d, (x0, y), (x1, y), 2.2, (165, 170, 182))
    elif kind in ("rain", "drizzle"):
        _cloud(d, grey, dy=-3)
        xs, length = ((11, 17.5, 24), 4.5) if kind == "rain" else ((13, 22), 3)
        for x in xs:
            _line(d, (x, 19.2), (x - 1.5, 19.2 + length), 1.6, (80, 160, 255))
    elif kind == "snow":
        _cloud(d, grey, dy=-3)
        for x, y in ((11, 20.2), (17.5, 22.2), (24, 20.2)):
            _ellipse(d, x, y, 1.2, (255, 255, 255))
    else:  # storm
        _cloud(d, dark, dy=-4)
        d.polygon([(p[0] * SS, p[1] * SS) for p in ((18.5, 13.5), (12.5, 19.5), (16, 19.5), (14, 23.8), (21, 17), (17.5, 17), (20.5, 13.5))], fill=(255, 215, 40))
    return image.resize((width, height), Image.Resampling.BOX)


# --------------------------------------------------------------------------- #
#  Utilidades de temperatura
# --------------------------------------------------------------------------- #
def temp_color(celsius: float) -> Color:
    """
    @brief Color de la temperatura según lo fría o caliente que sea.
    @param celsius Temperatura en °C.
    @return Color RGB (azul hielo si hace frío ... rojo si hace mucho calor).
    """
    for limit, color in ((0, (150, 200, 255)), (10, (80, 160, 255)), (18, (80, 220, 200)), (25, (255, 220, 80)), (32, (255, 150, 40))):
        if celsius <= limit:
            return color
    return (255, 70, 50)


def _degrees(celsius: float) -> int:
    """
    @brief Redondea una temperatura en °C al entero más cercano.
    @param celsius Temperatura en °C.
    @return Temperatura entera (nunca -0).
    """
    return int(round(celsius)) + 0


def _draw_degree(d: ImageDraw.ImageDraw, x: int, y: int, color: Color) -> None:
    """@brief Dibuja el símbolo de grados (un pequeño anillo de 5x5 píxeles) con la esquina superior izquierda en (x, y)."""
    d.rectangle((x + 1, y, x + 3, y), fill=color)
    d.rectangle((x + 1, y + 4, x + 3, y + 4), fill=color)
    d.rectangle((x, y + 1, x, y + 3), fill=color)
    d.rectangle((x + 4, y + 1, x + 4, y + 3), fill=color)


class WeatherScene(Scene):
    """
    @brief Escena "El tiempo".

    @par Ajustes
    - style: "now" (icono, temperatura y mínima/máxima de hoy) o "forecast" (hoy y los dos días siguientes).

    Las temperaturas se muestran siempre en grados Celsius.
    """

    ## Identificador de la escena.
    name = "weather"
    ## Nombre visible en la interfaz.
    label = "El tiempo"
    ## Ajustes configurables por el usuario.
    settings_schema = {
        "style": {
            "type": "choice",
            "default": "now",
            "label": "Estilo",
            "choices": [
                {"value": "now", "label": "Ahora"},
                {"value": "forecast", "label": "3 días"},
            ],
        },
    }

    def __init__(self, poller: "WeatherPoller") -> None:
        """
        @brief Crea la escena.
        @param poller Fuente de los datos del tiempo.
        """
        super().__init__()
        ## Fuente de datos.
        self.poller = poller
        ## Últimos datos leídos (None si no hay o están caducados).
        self._data: "WeatherData | None" = None
        ## Clave del último fotograma dibujado.
        self._cache_key: tuple | None = None
        ## Último fotograma dibujado.
        self._cache_image: Image.Image | None = None

    def update(self, dt: float) -> None:
        """
        @brief Lee los últimos datos del tiempo.
        @param dt Segundos desde el fotograma anterior (no se usa).
        """
        self._data = self.poller.snapshot()

    def render(self, size: int) -> Image.Image:
        """
        @brief Dibuja el tiempo, reutilizando el fotograma anterior si los datos no han cambiado.
        @param size Lado del fotograma en píxeles (el diseño es de 64 y se escala si es otro).
        @return Fotograma RGB. Es un objeto compartido con la caché: no hay que modificarlo.
        """
        key = (self.settings["style"], size, self._data)
        if key == self._cache_key and self._cache_image is not None:
            return self._cache_image

        if self._data is None:
            frame = self._render_empty()
        elif self.settings["style"] == "forecast":
            frame = self._render_forecast(self._data)
        else:
            frame = self._render_now(self._data)
        if size != REF_SIZE:
            frame = frame.resize((size, size), Image.Resampling.NEAREST)
        self._cache_key, self._cache_image = key, frame
        return frame

    def _fmt(self, celsius: float) -> str:
        """@brief Temperatura en °C como texto ("-3", "21"...)."""
        return str(_degrees(celsius))

    def _render_empty(self) -> Image.Image:
        """
        @brief Pantalla cuando todavía no hay datos (sin conexión o recién arrancado).
        @return Fotograma RGB de 64x64.
        """
        image = Image.new("RGB", (REF_SIZE, REF_SIZE), (0, 0, 0))
        icon = make_icon("overcast", True, 28, 21)
        image.paste(Image.eval(icon, lambda v: v // 3), (18, 14))
        draw_centered(ImageDraw.Draw(image), REF_SIZE / 2, 40, "SIN DATOS", 1, GRAY)
        return image

    def _render_now(self, data: "WeatherData") -> Image.Image:
        """
        @brief Estilo "Ahora": icono arriba, temperatura grande en el centro y mínima/máxima de hoy debajo.
        @param data Datos del tiempo.
        @return Fotograma RGB de 64x64.
        """
        image = Image.new("RGB", (REF_SIZE, REF_SIZE), (0, 0, 0))
        image.paste(make_icon(icon_kind(data.code), data.is_day, 28, 21), (18, 8))
        draw = ImageDraw.Draw(image)

        text = self._fmt(data.temp)
        color = temp_color(data.temp)
        total = text_width(text, 3, 2) + 2 + 5
        x = (REF_SIZE - total) // 2
        draw_text(draw, x, 31, text, 3, color, spacing=2)
        _draw_degree(draw, x + text_width(text, 3, 2) + 2, 31, color)

        today = data.days[0]
        low, high = self._fmt(today.tmin), self._fmt(today.tmax)
        total = text_width(low, 1) + 4 + text_width("/", 1) + 4 + text_width(high, 1)
        x = (REF_SIZE - total) // 2
        draw_text(draw, x, 50, low, 1, COLD)
        x += text_width(low, 1) + 4
        draw_text(draw, x, 50, "/", 1, GRAY)
        x += text_width("/", 1) + 4
        draw_text(draw, x, 50, high, 1, HOT)
        return image

    def _render_forecast(self, data: "WeatherData") -> Image.Image:
        """
        @brief Estilo "3 días": tres columnas (hoy y los dos días siguientes) con día, icono, máxima y mínima.
        @param data Datos del tiempo.
        @return Fotograma RGB de 64x64.
        """
        image = Image.new("RGB", (REF_SIZE, REF_SIZE), (0, 0, 0))
        draw = ImageDraw.Draw(image)
        for index, day in enumerate(data.days[:3]):
            cx = 16 + index * 16
            label = "HOY" if index == 0 else DAYS[datetime.strptime(day.date, "%Y-%m-%d").weekday()]
            draw_centered(draw, cx, 14, label, 1, (235, 235, 235) if index == 0 else GRAY)
            image.paste(make_icon(icon_kind(day.code), True, 16, 12), (cx - 8, 21))
            draw_centered(draw, cx, 38, self._fmt(day.tmax), 1, HOT)
            draw_centered(draw, cx, 45, self._fmt(day.tmin), 1, COLD)
        return image
