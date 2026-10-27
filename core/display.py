"""
@file display.py
@brief Salidas de vídeo: la matriz LED real y una simulada que guarda PNG.
"""
from __future__ import annotations

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

class MatrixDisplay:
    """
    @brief Salida hacia la matriz RGB real mediante hzeller/rpi-rgb-led-matrix.
    """

    def __init__(self, args: argparse.Namespace) -> None:
        """
        @brief Configura y abre la matriz.
        @param args Argumentos de línea de comandos (rows, cols, brightness, gpio_slowdown...).
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
        options.rows = args.rows
        options.cols = args.cols
        options.chain_length = args.chain_length
        options.parallel = args.parallel
        options.brightness = args.brightness
        options.gpio_slowdown = args.gpio_slowdown
        options.hardware_mapping = args.hardware_mapping
        options.pwm_bits = args.pwm_bits
        options.limit_refresh_rate_hz = args.limit_refresh_rate_hz
        options.disable_hardware_pulsing = args.no_hardware_pulse
        options.drop_privileges = args.drop_privileges

        ## Objeto RGBMatrix de la librería nativa.
        self.matrix = RGBMatrix(options=options)
        ## Lienzo secundario para dibujar sin parpadeo (doble búfer).
        self.canvas = self.matrix.CreateFrameCanvas()

    def show(self, image: Image.Image) -> None:
        """
        @brief Muestra una imagen en la matriz, sincronizada con el refresco (VSync).
        @param image Fotograma a mostrar.
        """
        self.canvas.SetImage(image.convert("RGB"))
        self.canvas = self.matrix.SwapOnVSync(self.canvas)

    def clear(self) -> None:
        """@brief Apaga todos los LEDs."""
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