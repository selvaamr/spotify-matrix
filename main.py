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

from core.display import MatrixDisplay, MockDisplay
from core.manager import SceneManager
from scenes.spotify_record import SpotifyRecordScene, demo_album_art, render_record
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
    @brief Genera cuatro fotogramas de ejemplo del disco girando (0, 45, 90 y 135 grados).
    @param directory Carpeta donde se guardan los PNG (se crea si no existe).
    """
    directory.mkdir(parents=True, exist_ok=True)
    art = demo_album_art(96)
    for index, angle in enumerate((0, 45, 90, 135)):
        render_record(art, angle, 64).save(directory / f"album-disk-{index:02d}.png")


def build_parser() -> argparse.ArgumentParser:
    """
    @brief Define los argumentos de línea de comandos.
    @return Parser de argparse configurado.
    """
    parser = argparse.ArgumentParser(description="Spin Spotify album art on a 64x64 RGB matrix.")
    parser.add_argument("--rows", type=int, default=64)
    parser.add_argument("--cols", type=int, default=64)
    parser.add_argument("--chain-length", type=int, default=1)
    parser.add_argument("--parallel", type=int, default=1)
    parser.add_argument("--brightness", type=int, default=65)
    parser.add_argument("--gpio-slowdown", type=int, default=2)
    parser.add_argument("--hardware-mapping", default="regular")
    parser.add_argument("--pwm-bits", type=int, default=11)
    parser.add_argument("--limit-refresh-rate-hz", type=int, default=120)
    parser.add_argument("--no-hardware-pulse", action="store_true",
                        help="Avoid Pi onboard sound conflict at the cost of more possible flicker.")
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
    parser.add_argument("--drop-privileges", action="store_true",
                        help="Soltar root tras iniciar la matriz (impide escribir el token de Spotify).")
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
        manager.register(SpotifyRecordScene(poller, rpm=args.rpm))
        manager.set_scene("spotify_record")

    display = MockDisplay(args.mock_output) if args.mock_output else MatrixDisplay(args)
    size = min(args.rows, args.cols)
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
