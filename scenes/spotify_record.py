"""
@file spotify_record.py
@brief Escena que muestra la carátula del disco actual girando, con varios diseños a elegir.

Cada diseño se compone de tres capas:
  -# **base**: fondo estático bajo la carátula (p. ej. los surcos del vinilo);
  -# **carátula**: la única parte que se rota en cada fotograma;
  -# **top**: capa estática por encima (brillos, agujero, aros...).

Las capas estáticas se dibujan con supersampling (a mayor resolución y luego se
reducen, para bordes suaves) **una sola vez** y se guardan en caché. Además se
guardan los fotogramas ya dibujados (uno por grado de giro): tras la primera vuelta
del disco ya no hay que calcular nada y el consumo de CPU es prácticamente nulo,
lo que ayuda a que la matriz no parpadee.
"""
from __future__ import annotations

import colorsys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from core.scene import Scene

if TYPE_CHECKING:
    from services.spotify import SpotifyPoller

## Factor de supersampling con el que se dibujan las capas estáticas.
SS = 4

## Tamaño de referencia (en píxeles) en el que están pensadas todas las medidas de los diseños.
REF_SIZE = 64.0

## Factor con el que se rota la carátula (se gira al doble de resolución y se reduce, lo que
## evita que quede "blanda" en ángulos intermedios). Ponlo a 1 si la Raspberry Pi va justa.
ROTATION_SUPERSAMPLE = 2

## Paso (en grados) con el que se redondea el ángulo para reutilizar fotogramas ya dibujados.
ANGLE_STEP_DEG = 1.0

## Diseño usado por defecto.
DEFAULT_STYLE = "cover"

## Color RGB.
Color = tuple[int, int, int]


# --------------------------------------------------------------------------- #
#  Utilidades de color
# --------------------------------------------------------------------------- #
def _dominant_color(art: Image.Image) -> Color:
    """
    @brief Calcula el color dominante de una carátula, avivado para que destaque en los LEDs.
    @param art Carátula del álbum.
    @return Color RGB con saturación y brillo mínimos garantizados.
    """
    r, g, b = art.convert("RGB").resize((1, 1), Image.Resampling.BOX).getpixel((0, 0))
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    s, v = max(s, 0.65), max(v, 0.85)
    return tuple(int(c * 255) for c in colorsys.hsv_to_rgb(h, s, v))  # type: ignore[return-value]


def _scale_color(color: Color, factor: float) -> Color:
    """
    @brief Oscurece o aclara un color multiplicando sus canales.
    @param color  Color RGB original.
    @param factor Multiplicador (menor que 1 oscurece, mayor que 1 aclara).
    @return Nuevo color RGB, limitado a 255 por canal.
    """
    return tuple(int(min(255, ch * factor)) for ch in color)  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
#  Pintor de capas
# --------------------------------------------------------------------------- #
class _Painter:
    """
    @brief Lienzo RGBA con supersampling para dibujar capas estáticas.

    Todas las medidas se expresan en "unidades de diseño" (como si la matriz
    fuera de 64x64) y se escalan automáticamente al tamaño real.
    """

    def __init__(self, size: int, background: tuple[int, int, int, int]) -> None:
        """
        @brief Crea el lienzo.
        @param size       Lado final de la capa en píxeles.
        @param background Color RGBA de fondo (alfa 0 para una capa transparente).
        """
        ## Lado final de la capa en píxeles.
        self.size = size
        ## Píxeles reales (a resolución final) que mide cada unidad de diseño.
        self.k = size / REF_SIZE
        ## Lado del lienzo con supersampling.
        self.n = size * SS
        ## Imagen RGBA a resolución ampliada.
        self.img = Image.new("RGBA", (self.n, self.n), background)
        ## Objeto de dibujo asociado a la imagen.
        self.draw = ImageDraw.Draw(self.img)

    def _px(self, units: float) -> float:
        """
        @brief Convierte unidades de diseño a píxeles del lienzo ampliado.
        @param units Medida en unidades de diseño.
        @return Medida en píxeles ampliados.
        """
        return units * self.k * SS

    def circle(self, radius: float, fill: tuple[int, ...]) -> None:
        """
        @brief Dibuja un círculo relleno centrado.
        @param radius Radio en unidades de diseño.
        @param fill   Color de relleno (RGB o RGBA).
        """
        c, r = self.n / 2, self._px(radius)
        self.draw.ellipse((c - r, c - r, c + r, c + r), fill=fill)

    def ring(self, radius: float, width: float, fill: tuple[int, ...]) -> None:
        """
        @brief Dibuja una corona (círculo hueco) centrada; el grosor crece hacia dentro.
        @param radius Radio exterior en unidades de diseño.
        @param width  Grosor en unidades de diseño.
        @param fill   Color del trazo (RGB o RGBA).
        """
        c, r = self.n / 2, self._px(radius)
        self.draw.ellipse((c - r, c - r, c + r, c + r), outline=fill, width=max(1, int(round(self._px(width)))))

    def _disc_mask(self, radius: float) -> Image.Image:
        """
        @brief Crea una máscara en escala de grises con un círculo blanco centrado.
        @param radius Radio en unidades de diseño.
        @return Imagen "L" del tamaño del lienzo ampliado.
        """
        mask = Image.new("L", (self.n, self.n), 0)
        c, r = self.n / 2, self._px(radius)
        ImageDraw.Draw(mask).ellipse((c - r, c - r, c + r, c + r), fill=255)
        return mask

    def _composite(self, overlay: Image.Image) -> None:
        """
        @brief Superpone una capa RGBA (respetando su transparencia) sobre el lienzo.
        @param overlay Capa RGBA del mismo tamaño que el lienzo.
        """
        self.img = Image.alpha_composite(self.img, overlay)
        self.draw = ImageDraw.Draw(self.img)

    def sheen(self, radius: float, alpha: int, wedges: tuple[tuple[int, int], ...] = ((295, 335), (115, 155))) -> None:
        """
        @brief Añade reflejos de luz suaves y estáticos (dos cuñas opuestas), como en un disco real.
        @param radius Radio del disco sobre el que se aplican, en unidades de diseño.
        @param alpha  Intensidad del reflejo (0 a 255).
        @param wedges Pares (ángulo inicial, ángulo final) en grados de cada cuña.
        """
        c, r = self.n / 2, self._px(radius)
        light = Image.new("L", (self.n, self.n), 0)
        draw = ImageDraw.Draw(light)
        for start, end in wedges:
            draw.pieslice((c - r, c - r, c + r, c + r), start, end, fill=alpha)
        # Se difumina solo el alfa, para que el borde del reflejo no se ensucie de negro.
        light = light.filter(ImageFilter.GaussianBlur(SS * 1.2 * self.k))
        light = ImageChops.multiply(light, self._disc_mask(radius))
        overlay = Image.new("RGBA", (self.n, self.n), (255, 255, 255, 0))
        overlay.putalpha(light)
        self._composite(overlay)

    def finish(self) -> Image.Image:
        """
        @brief Reduce el lienzo ampliado al tamaño final con suavizado.
        @return Capa RGBA de size x size píxeles.
        """
        return self.img.resize((self.size, self.size), Image.Resampling.LANCZOS)


# --------------------------------------------------------------------------- #
#  Capas de un diseño
# --------------------------------------------------------------------------- #
@dataclass
class _Layers:
    """
    @brief Capas estáticas ya preparadas de un diseño (ver @ref spotify_record.py).
    """

    ## Fondo opaco, bajo la carátula.
    base: Image.Image
    ## Capa transparente por encima de la carátula (brillos, agujero, aros).
    top: Image.Image
    ## Máscara circular suavizada que recorta la carátula.
    mask: Image.Image
    ## Diámetro en píxeles del disco de carátula.
    art_dia: int


def _make_layers(size: int, base: _Painter, top: _Painter, art_radius: float) -> _Layers:
    """
    @brief Termina los pintores y prepara la máscara circular de la carátula.
    @param size       Lado final en píxeles.
    @param base       Pintor de la capa base.
    @param top        Pintor de la capa superior.
    @param art_radius Radio del disco de carátula en unidades de diseño.
    @return Capas listas para usar en cada fotograma.
    """
    dia = int(round(2 * art_radius * size / REF_SIZE))
    if (size - dia) % 2:  # mismo "paridad" que size, para que el disco quede centrado al píxel
        dia += 1
    mask = Image.new("L", (dia * SS, dia * SS), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, dia * SS - 1, dia * SS - 1), fill=255)
    mask = mask.resize((dia, dia), Image.Resampling.LANCZOS)
    return _Layers(base.finish(), top.finish(), mask, dia)


def _painters(size: int) -> tuple[_Painter, _Painter]:
    """
    @brief Crea el par de pintores (base opaca negra, capa superior transparente).
    @param size Lado final en píxeles.
    @return Tupla (pintor base, pintor superior).
    """
    return _Painter(size, (0, 0, 0, 255)), _Painter(size, (0, 0, 0, 0))


def _draw_vinyl_surface(
    p: _Painter,
    outer: float,
    label: float,
    body: tuple[int, ...],
    dark: tuple[int, ...],
    light: tuple[int, ...],
    rim: tuple[int, ...],
) -> None:
    """
    @brief Dibuja el cuerpo de un vinilo: disco, surcos concéntricos alternos y borde.
    @param p     Pintor sobre el que dibujar.
    @param outer Radio exterior del disco (unidades de diseño).
    @param label Radio de la etiqueta central (los surcos empiezan justo fuera).
    @param body  Color del cuerpo del disco.
    @param dark  Color de los surcos oscuros.
    @param light Color de los surcos claros.
    @param rim   Color del borde exterior.
    """
    p.circle(outer, body)
    radius, use_light = label + 2, False
    while radius < outer - 0.5:
        p.ring(radius, 0.5, light if use_light else dark)
        radius += 1.5
        use_light = not use_light
    p.ring(outer, 0.8, rim)


# --------------------------------------------------------------------------- #
#  Diseños
# --------------------------------------------------------------------------- #
def _build_vinyl(size: int, dominant: Color) -> _Layers:
    """
    @brief Diseño A, "Vinilo clásico": disco negro con surcos; la carátula es la etiqueta central.
    @param size     Lado en píxeles.
    @param dominant Color dominante de la carátula (no se usa en este diseño).
    @return Capas del diseño.
    """
    outer, label = REF_SIZE / 2 - 1, REF_SIZE * 0.30
    base, top = _painters(size)
    _draw_vinyl_surface(base, outer, label, (12, 12, 12, 255), (20, 20, 20, 255), (34, 34, 34, 255), (50, 50, 50, 255))
    top.ring(label, 0.7, (0, 0, 0, 255))
    top.circle(1.6, (0, 0, 0, 255))
    top.circle(0.8, (190, 190, 190, 255))
    top.sheen(outer, 34)
    return _make_layers(size, base, top, label)


def _build_cover(size: int, dominant: Color) -> _Layers:
    """
    @brief Diseño B, "Portada + brillo": carátula completa con reflejo de luz y agujero plateado.
    @param size     Lado en píxeles.
    @param dominant Color dominante de la carátula (no se usa en este diseño).
    @return Capas del diseño.
    """
    outer = REF_SIZE / 2 - 1
    base, top = _painters(size)
    top.ring(outer, 0.8, (8, 8, 8, 255))
    top.sheen(outer, 55)
    top.circle(3.2, (0, 0, 0, 255))
    top.ring(3.2, 0.7, (200, 200, 200, 190))
    return _make_layers(size, base, top, outer)


def _build_cd(size: int, dominant: Color) -> _Layers:
    """
    @brief Diseño C, "CD": carátula completa con el aro transparente de plástico y el agujero central.
    @param size     Lado en píxeles.
    @param dominant Color dominante de la carátula (no se usa en este diseño).
    @return Capas del diseño.
    """
    outer = REF_SIZE / 2 - 1
    base, top = _painters(size)
    top.circle(11, (215, 215, 225, 110))   # aro de plástico transparente
    top.ring(11, 0.7, (240, 240, 245, 170))
    top.circle(4.5, (0, 0, 0, 255))        # agujero
    return _make_layers(size, base, top, outer)


def _build_color_vinyl(size: int, dominant: Color) -> _Layers:
    """
    @brief Diseño E, "Vinilo de color": como el clásico, pero con el color dominante de cada portada.
    @param size     Lado en píxeles.
    @param dominant Color dominante de la carátula actual.
    @return Capas del diseño.
    """
    outer, label = REF_SIZE / 2 - 1, REF_SIZE * 0.28
    base, top = _painters(size)
    _draw_vinyl_surface(
        base, outer, label,
        _scale_color(dominant, 0.45) + (255,),
        _scale_color(dominant, 0.38) + (255,),
        _scale_color(dominant, 0.62) + (255,),
        _scale_color(dominant, 0.25) + (255,),
    )
    top.ring(label, 0.7, (0, 0, 0, 255))
    top.circle(1.6, (0, 0, 0, 255))
    top.circle(0.8, (230, 230, 230, 255))
    top.sheen(outer, 45)
    return _make_layers(size, base, top, label)


## Diseños disponibles: identificador -> (nombre visible, función que construye sus capas).
STYLES: dict[str, tuple[str, Callable[[int, Color], _Layers]]] = {
    "vinyl": ("Vinilo clásico", _build_vinyl),
    "cover": ("Portada + brillo", _build_cover),
    "cd": ("CD", _build_cd),
    "color_vinyl": ("Vinilo de color", _build_color_vinyl),
}

## Diseños cuyas capas dependen del color dominante (hay que reconstruirlas al cambiar de canción).
_STYLES_USING_DOMINANT = {"color_vinyl"}


# --------------------------------------------------------------------------- #
#  Renderizado
# --------------------------------------------------------------------------- #
class RecordRenderer:
    """
    @brief Dibuja el disco con caché de capas estáticas y de fotogramas.

    Las capas se reconstruyen solo cuando cambia el diseño, el tamaño o (en los
    diseños que lo usan) la carátula. Los fotogramas ya dibujados se reutilizan
    (el ángulo se redondea a ANGLE_STEP_DEG), así que tras la primera vuelta no
    se calcula nada más. La imagen devuelta es compartida: no hay que modificarla.
    """

    def __init__(self) -> None:
        """@brief Crea un renderizador con la caché vacía."""
        ## Última carátula procesada (se compara por identidad, no por contenido).
        self._art_ref: Image.Image | None = None
        ## Color dominante de la última carátula.
        self._dominant: Color = (255, 255, 255)
        ## Carátula recortada a cuadrado, a ROTATION_SUPERSAMPLE veces el tamaño del disco, lista para rotar.
        self._art_square: Image.Image | None = None
        ## Capas estáticas en uso.
        self._layers: _Layers | None = None
        ## Clave (diseño, tamaño, color) con la que se construyeron las capas.
        self._layers_key: tuple | None = None
        ## Fotogramas ya dibujados (ángulo redondeado -> imagen) de la carátula y diseño actuales.
        self._frames: dict[int, Image.Image] = {}

    def render(self, art: Image.Image, angle: float, size: int, style: str = DEFAULT_STYLE) -> Image.Image:
        """
        @brief Dibuja un fotograma del disco.
        @param art   Carátula del álbum.
        @param angle Ángulo de giro en grados.
        @param size  Lado del fotograma en píxeles.
        @param style Identificador del diseño (ver STYLES); si no existe se usa DEFAULT_STYLE.
        @return Fotograma RGB de size x size (objeto compartido con la caché; no modificar).
        """
        if style not in STYLES:
            style = DEFAULT_STYLE

        if art is not self._art_ref:
            self._art_ref = art
            self._dominant = _dominant_color(art)
            self._art_square = None
            self._frames.clear()

        key = (style, size, self._dominant if style in _STYLES_USING_DOMINANT else None)
        if key != self._layers_key or self._layers is None:
            self._layers = STYLES[style][1](size, self._dominant)
            self._layers_key = key
            self._art_square = None
            self._frames.clear()

        steps = int(round(360.0 / ANGLE_STEP_DEG))
        slot = int(round(angle / ANGLE_STEP_DEG)) % steps
        cached = self._frames.get(slot)
        if cached is not None:
            return cached

        layers = self._layers
        if self._art_square is None:
            big = layers.art_dia * ROTATION_SUPERSAMPLE
            self._art_square = ImageOps.fit(art.convert("RGB"), (big, big), method=Image.Resampling.LANCZOS)

        frame = layers.base.copy()
        rotated = self._art_square.rotate(slot * ANGLE_STEP_DEG, resample=Image.Resampling.BICUBIC)
        if ROTATION_SUPERSAMPLE > 1:
            rotated = rotated.resize((layers.art_dia, layers.art_dia), Image.Resampling.BOX)
        rotated = rotated.convert("RGBA")
        offset = (size - layers.art_dia) // 2
        frame.paste(rotated, (offset, offset), layers.mask)
        result = Image.alpha_composite(frame, layers.top).convert("RGB")
        self._frames[slot] = result
        return result


def render_record(art: Image.Image | None, angle: float, size: int, style: str = DEFAULT_STYLE) -> Image.Image:
    """
    @brief Dibuja un único fotograma del disco, sin caché (útil para pruebas y vistas previas).
    @param art   Carátula del álbum (None para un fotograma negro).
    @param angle Ángulo de giro en grados.
    @param size  Lado del fotograma en píxeles.
    @param style Identificador del diseño (ver STYLES).
    @return Fotograma RGB de size x size.
    """
    if art is None:
        return Image.new("RGB", (size, size), (0, 0, 0))
    return RecordRenderer().render(art, angle, size, style)


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


# --------------------------------------------------------------------------- #
#  Escena
# --------------------------------------------------------------------------- #
class SpotifyRecordScene(Scene):
    """
    @brief Escena "Disco de Spotify": la carátula gira mientras la música suena.

    @par Ajustes
    - rpm: velocidad de giro en revoluciones por minuto (1 a 120).
    - style: diseño del disco (vinyl, cover, cd o color_vinyl).

    @note Devuelve imágenes compartidas con la caché: quien las reciba no debe modificarlas.
    """

    ## Identificador de la escena.
    name = "spotify_record"
    ## Nombre visible en la interfaz.
    label = "Disco de Spotify"
    ## Ajustes configurables por el usuario.
    settings_schema = {
        "rpm": {"type": "float", "min": 1.0, "max": 120.0, "default": 20.0, "label": "Velocidad (rpm)"},
        "style": {
            "type": "choice",
            "default": DEFAULT_STYLE,
            "label": "Diseño del disco",
            "choices": [{"value": key, "label": label} for key, (label, _) in STYLES.items()],
        },
    }

    def __init__(self, poller: "SpotifyPoller", rpm: float = 20.0, style: str = DEFAULT_STYLE) -> None:
        """
        @brief Crea la escena.
        @param poller Fuente de la carátula y del estado de reproducción.
        @param rpm    Velocidad inicial de giro.
        @param style  Diseño inicial del disco (ver STYLES).
        """
        super().__init__()
        ## Fuente de datos de Spotify.
        self.poller = poller
        self.configure(rpm=rpm, style=style)
        ## Ángulo actual del disco en grados.
        self.angle = 0.0
        ## Última carátula leída del poller.
        self._image: Image.Image | None = None
        ## Renderizador con caché de capas y fotogramas.
        self._renderer = RecordRenderer()
        ## Disco vacío ya dibujado (tamaño, imagen), para no regenerarlo en cada fotograma.
        self._idle: tuple[int, Image.Image] | None = None

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
        @brief Dibuja el disco girando con el diseño elegido, o el disco vacío si no hay carátula.
        @param size Lado del fotograma en píxeles.
        @return Fotograma RGB.
        """
        if self._image is None:
            if self._idle is None or self._idle[0] != size:
                self._idle = (size, render_idle(size))
            return self._idle[1]
        return self._renderer.render(self._image, self.angle, size, self.settings["style"])