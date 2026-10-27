"""
@file display.py
@brief Salidas de vídeo: la matriz LED real y una simulada que guarda PNG.

La configuración física de la matriz (tamaño, pines, refresco...) está fija en las
constantes de este archivo, porque el hardware no cambia. Si algún día tocas el
montaje (otro panel, otro HAT), se cambia aquí y no hace falta pasar nada por comando.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

## Filas del panel.
ROWS = 64
## Columnas del panel.
COLS = 64
## Paneles encadenados en serie.
CHAIN_LENGTH = 1
## Cadenas de paneles en paralelo.
PARALLEL = 1
## Mapeo de pines. "adafruit-hat-pwm" es el que corresponde al HAT con el puente GPIO4-GPIO18
## soldado (modo calidad). Sin el puente habría que usar "adafruit-hat".
HARDWARE_MAPPING = "adafruit-hat-pwm"
## Retardo de acceso a los GPIO; depende del modelo de Raspberry Pi (4 es lo habitual en una Pi 4).
GPIO_SLOWDOWN = 4
## Bits de PWM (1 a 11). Menos bits = más refresco y menos parpadeo, a cambio de menos matices de color.
PWM_BITS = 11
## Límite superior de refresco, en Hz.
LIMIT_REFRESH_RATE_HZ = 120
## Debe ser False con el puente soldado (se usa el PWM por hardware). Requiere el audio de la placa desactivado.
DISABLE_HARDWARE_PULSING = False
## Si es False, el proceso conserva root: soltarlo impediría escribir el token de Spotify en .cache.
DROP_PRIVILEGES = False
## Brillo por defecto (0 a 100).
DEFAULT_BRIGHTNESS = 65

## Lado en píxeles del fotograma que se dibuja (la matriz es cuadrada).
MATRIX_SIZE = min(ROWS, COLS)


class MatrixDisplay:
    """
    @brief Salida hacia la matriz RGB real mediante hzeller/rpi-rgb-led-matrix.
    """

    def __init__(self, brightness: int = DEFAULT_BRIGHTNESS) -> None:
        """
        @brief Configura y abre la matriz con los parámetros fijos de este archivo.
        @param brightness Brillo de 0 a 100.
        @throws RuntimeError si no están instalados los bindings de rgbmatrix.
        """
        try:
            from rgbmatrix import RGBMatrix, RGBMatrixOptions
        except ImportError as exc:
            raise RuntimeError(
                "The rgbmatrix Python bindings are not installed. "
                "Install hzeller/rpi-rgb-led-matrix on the Pi, or run with --mock-output."
            ) from exc

        options = RGBMatrixOptions()
        options.rows = ROWS
        options.cols = COLS
        options.chain_length = CHAIN_LENGTH
        options.parallel = PARALLEL
        options.brightness = brightness
        options.gpio_slowdown = GPIO_SLOWDOWN
        options.hardware_mapping = HARDWARE_MAPPING
        options.pwm_bits = PWM_BITS
        options.limit_refresh_rate_hz = LIMIT_REFRESH_RATE_HZ
        options.disable_hardware_pulsing = DISABLE_HARDWARE_PULSING
        options.drop_privileges = DROP_PRIVILEGES

        ## Objeto RGBMatrix de la librería nativa.
        self.matrix = RGBMatrix(options=options)
        ## Lienzo secundario para dibujar sin parpadeo (doble búfer).
        self.canvas = self.matrix.CreateFrameCanvas()
        ## Última imagen enviada a la matriz (para no repetir el trabajo si no ha cambiado).
        self._last_image: Image.Image | None = None

    def show(self, image: Image.Image) -> None:
        """
        @brief Muestra una imagen en la matriz, sincronizada con el refresco (VSync).

        Si es exactamente el mismo objeto imagen que el fotograma anterior (p. ej. el
        disco en pausa) no se hace nada: la matriz ya lo está mostrando.

        @param image Fotograma a mostrar.
        """
        if image is self._last_image:
            return
        self._last_image = image
        self.canvas.SetImage(image.convert("RGB"))
        self.canvas = self.matrix.SwapOnVSync(self.canvas)

    def clear(self) -> None:
        """@brief Apaga todos los LEDs."""
        self._last_image = None
        self.matrix.Clear()


class MockDisplay:
    """
    @brief Pantalla simulada que guarda cada fotograma en un PNG.

    Permite desarrollar y depurar sin tener la matriz delante.
    """

    def __init__(self, output: Path) -> None:
        """
        @brief Prepara el archivo de salida.
        @param output Ruta del PNG que se sobrescribirá en cada fotograma.
        """
        ## Ruta del PNG de salida.
        self.output = output
        self.output.parent.mkdir(parents=True, exist_ok=True)

    def show(self, image: Image.Image) -> None:
        """
        @brief Guarda el fotograma en disco.
        @param image Fotograma a guardar.
        """
        image.save(self.output)

    def clear(self) -> None:
        """@brief No hace nada (no hay LEDs que apagar)."""
        return