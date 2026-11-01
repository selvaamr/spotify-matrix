#!/usr/bin/env python3
"""
@file main.py
@brief Punto de entrada: lee los argumentos, crea pantalla, escenas y ejecuta el bucle principal.

Además de dibujar, arranca la interfaz web (ver web/server.py) en un hilo aparte.
Los ajustes (escena, velocidad, diseño, brillo...) se cambian desde la web y se
guardan en settings.json, por lo que el comando de arranque no necesita parámetros.
El tiempo se descarga de Open-Meteo en segundo plano (ver services/weather.py).

@par Uso
@code
sudo -E .venv/bin/python main.py                  # arranque normal (matriz + web)
python3 main.py --no-spotify --mock-output out/frame.png --once   # prueba sin hardware ni Spotify
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

from core.controller import Controller
from core.display import MATRIX_SIZE, MatrixDisplay, MockDisplay
from core.manager import SceneManager
from core.notes import NotesStore
from core.pixelart import PixelArtStore
from core.preview import FramePublisher
from core.settings import SettingsStore
from scenes.calendar_scene import CalendarScene
from scenes.clock import ClockScene
from scenes.pixel_art import PixelArtScene
from scenes.spotify_record import STYLES, SpotifyRecordScene, demo_album_art, render_record
from scenes.weather import WeatherScene
from services.spotify import SpotifyClient, SpotifyPoller
from services.weather import poller_from_env

## Archivo donde se guardan los ajustes del usuario (junto a main.py, esté donde esté el directorio de trabajo).
SETTINGS_FILE = Path(__file__).resolve().parent / "settings.json"

## Archivo donde se guardan las notas del calendario (junto a main.py).
NOTES_FILE = Path(__file__).resolve().parent / "notes.json"

## Carpeta donde se guardan las imágenes de pixel art del usuario (junto a main.py).
PIXELART_DIR = Path(__file__).resolve().parent / "pixelart"

## Carpeta con las imágenes de pixel art que se copian la primera vez que se arranca.
PIXELART_DEFAULTS_DIR = Path(__file__).resolve().parent / "pixelart_defaults"


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
    parser.add_argument("--poll-seconds", type=positive_float, default=2.0)
    parser.add_argument("--fps", type=positive_float, default=20.0)
    parser.add_argument("--token-cache", type=Path, default=Path(".cache/spotify_token.json"))
    parser.add_argument("--mock-output", type=Path,
                        help="Write the current frame PNG instead of using RGB matrix hardware.")
    parser.add_argument("--preview-frames", type=Path,
                        help="Render sample spinning-album-art disk frames and exit.")
    parser.add_argument("--auth-only", action="store_true",
                        help="Authorize Spotify, cache the token, and exit without using the matrix.")
    parser.add_argument("--no-spotify", action="store_true",
                        help="No usar Spotify: solo las escenas de reloj, calendario y tiempo.")
    parser.add_argument("--once", action="store_true", help="Render one frame and exit.")
    parser.add_argument("--no-web", action="store_true", help="No arrancar la interfaz web.")
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


def start_web(controller: Controller, publisher: FramePublisher, notes: NotesStore, gallery: PixelArtStore):
    """
    @brief Arranca la interfaz web en segundo plano si las dependencias están instaladas.

    Si faltan fastapi o uvicorn no es un error: el programa sigue funcionando sin web.

    @param controller Controlador con el que se opera la matriz.
    @param publisher  Origen del fotograma para la vista previa.
    @param notes      Almacén de notas del calendario (se gestionan en la página /notas).
    @param gallery    Galería de pixel art (se gestiona en la página /imagenes).
    @return El servidor web en marcha, o None si no se ha podido arrancar.
    """
    try:
        from web.notes_api import create_notes_router
        from web.pixelart_api import create_pixelart_router
        from web.server import WebServer, create_app, local_urls

        app = create_app(controller, publisher)
        app.include_router(create_notes_router(notes))
        app.include_router(create_pixelart_router(gallery))
        server = WebServer(app)
    except ImportError as exc:
        print(f"Web desactivada, faltan dependencias ({exc}). Instala con: pip install fastapi uvicorn", flush=True)
        return None

    server.start()
    print("Interfaz web disponible en: " + "  o  ".join(local_urls(server.port)), flush=True)
    return server


def run(args: argparse.Namespace) -> None:
    """
    @brief Ejecuta el programa según los argumentos recibidos.

    Registra las escenas, restaura los ajustes guardados, arranca la web y ejecuta el
    bucle principal (update + render + show) hasta Ctrl+C, o un solo fotograma con --once.

    @param args Argumentos de línea de comandos ya interpretados.
    """
    if args.preview_frames:
        render_preview_frames(args.preview_frames)
        return

    load_dotenv()
    manager = SceneManager()
    poller: SpotifyPoller | None = None
    weather = poller_from_env()
    notes = NotesStore(NOTES_FILE)
    gallery = PixelArtStore(PIXELART_DIR)
    gallery.install_defaults(PIXELART_DEFAULTS_DIR)

    if args.no_spotify:
        manager.register(ClockScene())
        manager.register(CalendarScene(notes=notes))
        manager.register(WeatherScene(weather))
        manager.register(PixelArtScene(gallery))
        default_scene = "clock"
    else:
        spotify = build_spotify_client(args)
        if args.auth_only:
            spotify.authorize()
            print(f"Spotify token cached at {args.token_cache}")
            return
        poller = SpotifyPoller(spotify, args.poll_seconds)
        poller.start()
        manager.register(SpotifyRecordScene(poller))
        manager.register(ClockScene())
        manager.register(CalendarScene(notes=notes))
        manager.register(WeatherScene(weather))
        manager.register(PixelArtScene(gallery))
        default_scene = "spotify_record"

    if not args.once:
        weather.start()

    display = MockDisplay(args.mock_output) if args.mock_output else MatrixDisplay()
    controller = Controller(manager, SettingsStore(SETTINGS_FILE), display, default_scene)
    controller.restore()
    publisher = FramePublisher()
    web = None if (args.no_web or args.once) else start_web(controller, publisher, notes, gallery)

    size = MATRIX_SIZE
    last_frame = time.monotonic()

    try:
        while True:
            frame_start = time.monotonic()
            delta = frame_start - last_frame
            last_frame = frame_start

            manager.update(delta)
            frame = manager.render(size)
            publisher.publish(frame)
            display.show(frame)

            if args.once:
                break

            time.sleep(max(0.0, (1.0 / args.fps) - (time.monotonic() - frame_start)))
    except KeyboardInterrupt:
        pass
    finally:
        if web:
            web.stop()
        controller.shutdown()
        if poller:
            poller.stop()
        weather.stop()
        display.clear()


if __name__ == "__main__":
    run(build_parser().parse_args())
