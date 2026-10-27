#!/usr/bin/env python3
"""
@file main.py
@brief Punto de entrada: lee los argumentos, crea pantalla, escenas y ejecuta el bucle principal.

@par Uso
@code
python3 main.py                                   # disco de Spotify en la matriz
python3 main.py --test-pattern --mock-output out/frame.png --once
@endcode
"""
from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv() -> None:
        return None

from core.display import DEFAULT_BRIGHTNESS, MATRIX_SIZE, MatrixDisplay, MockDisplay
from core.manager import SceneManager
from scenes.spotify_record import DEFAULT_STYLE, STYLES, SpotifyRecordScene, demo_album_art, render_record
from scenes.test_pattern import TestPatternScene
from services.spotify import SpotifyClient, SpotifyPoller


def positive_float(value: str) -> float:
    """
    @brief Tipo de argumento de argparse para números estrictamente positivos.
    @param value Texto recibido por línea de comandos.
    @return Valor convertido a float.
    @throws argparse.ArgumentTypeError si el valor es menor o igual que cero.
    """
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def render_preview_frames(directory: Path) -> None:
    """
    @brief Genera fotogramas de ejemplo (0, 45, 90 y 135 grados) de cada diseño del disco.
    @param directory Carpeta donde se guardan los PNG (se crea si no existe).
    """
    directory.mkdir(parents=True, exist_ok=True)
    art = demo_album_art(96)
    for style in STYLES:
        for index, angle in enumerate((0, 45, 90, 135)):
            render_record(art, angle, 64, style).save(directory / f"album-disk-{style}-{index:02d}.png")


def build_parser() -> argparse.ArgumentParser:
    """
    @brief Define los argumentos de línea de comandos.
    @return Parser de argparse configurado.
    """
    parser = argparse.ArgumentParser(description="Spin Spotify album art on a 64x64 RGB matrix.")
    parser.add_argument("--brightness", type=int, default=DEFAULT_BRIGHTNESS)
    parser.add_argument("--style", choices=list(STYLES), default=DEFAULT_STYLE,
                        help="Diseño del disco: " + ", ".join(f"{k} ({v[0]})" for k, v in STYLES.items()))
    parser.add_argument("--poll-seconds", type=positive_float, default=2.0)
    parser.add_argument("--fps", type=positive_float, default=20.0)
    parser.add_argument("--rpm", type=positive_float, default=20.0)
    parser.add_argument("--token-cache", type=Path, default=Path(".cache/spotify_token.json"))
    parser.add_argument("--mock-output", type=Path,
                        help="Write the current frame PNG instead of using RGB matrix hardware.")
    parser.add_argument("--preview-frames", type=Path,
                        help="Render sample spinning-album-art disk frames and exit.")
    parser.add_argument("--auth-only", action="store_true",
                        help="Authorize Spotify, cache the token, and exit without using the matrix.")
    parser.add_argument("--test-pattern", action="store_true",
                        help="Show a bright moving color test pattern without using Spotify.")
    parser.add_argument("--once", action="store_true", help="Render one frame and exit.")
    parser.add_argument("--no-browser", action="store_true",
                        help="Print the Spotify auth URL without trying to open a browser.")
    return parser


def build_spotify_client(args: argparse.Namespace) -> SpotifyClient:
    """
    @brief Crea el cliente de Spotify con las credenciales del entorno (.env).

    Variables necesarias: SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET y, opcionalmente,
    SPOTIFY_REDIRECT_URI (por defecto http://127.0.0.1:8888/callback).

    @param args Argumentos de línea de comandos (token_cache, no_browser).
    @return Cliente de Spotify listo para usar.
    @throws SystemExit si falta alguna variable de entorno obligatoria.
    """
    client_id = os.environ.get("SPOTIFY_CLIENT_ID")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
    redirect_uri = os.environ.get("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")

    missing = [
        name
        for name, value in (
            ("SPOTIFY_CLIENT_ID", client_id),
            ("SPOTIFY_CLIENT_SECRET", client_secret),
            ("SPOTIFY_REDIRECT_URI", redirect_uri),
        )
        if not value
    ]
    if missing:
        raise SystemExit(f"Missing required environment values: {', '.join(missing)}")

    return SpotifyClient(
        client_id=client_id or "",
        client_secret=client_secret or "",
        redirect_uri=redirect_uri,
        token_cache=args.token_cache,
        open_browser=not args.no_browser,
    )


def run(args: argparse.Namespace) -> None:
    """
    @brief Ejecuta el programa según los argumentos recibidos.

    Registra las escenas, activa la inicial y ejecuta el bucle principal
    (update + render + show) hasta Ctrl+C, o un solo fotograma con --once.

    @param args Argumentos de línea de comandos ya interpretados.
    """
    if args.preview_frames:
        render_preview_frames(args.preview_frames)
        return

    load_dotenv()
    manager = SceneManager()
    poller: SpotifyPoller | None = None

    if args.test_pattern:
        manager.register(TestPatternScene())
        manager.set_scene("test_pattern")
    else:
        spotify = build_spotify_client(args)
        if args.auth_only:
            spotify.authorize()
            print(f"Spotify token cached at {args.token_cache}")
            return
        poller = SpotifyPoller(spotify, args.poll_seconds)
        poller.start()
        manager.register(SpotifyRecordScene(poller, rpm=args.rpm, style=args.style))
        manager.set_scene("spotify_record")

    display = MockDisplay(args.mock_output) if args.mock_output else MatrixDisplay(args.brightness)
    size = MATRIX_SIZE
    last_frame = time.monotonic()

    try:
        while True:
            frame_start = time.monotonic()
            delta = frame_start - last_frame
            last_frame = frame_start

            manager.update(delta)
            display.show(manager.render(size))

            if args.once:
                break

            time.sleep(max(0.0, (1.0 / args.fps) - (time.monotonic() - frame_start)))
    except KeyboardInterrupt:
        pass
    finally:
        if poller:
            poller.stop()
        display.clear()


if __name__ == "__main__":
    run(build_parser().parse_args())