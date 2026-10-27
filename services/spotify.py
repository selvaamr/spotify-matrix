"""
@file spotify.py
@brief Cliente de la API de Spotify (OAuth + "reproduciendo ahora") y sondeo en segundo plano.
"""
from __future__ import annotations

import base64
import json
import secrets
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from services.http_utils import http_request, raise_http_error

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
CURRENTLY_PLAYING_URL = "https://api.spotify.com/v1/me/player/currently-playing"
SCOPE = "user-read-currently-playing"


@dataclass
class PlaybackArt:
    """
    @brief Datos de la carátula de lo que suena ahora mismo.
    """

    ## Identificador de la canción/episodio (sirve para detectar cambios).
    key: str
    ## URL de la imagen de mayor resolución.
    image_url: str
    ## True si la reproducción está en marcha, False si está en pausa.
    is_playing: bool


class SpotifyClient:
    """
    @brief Cliente de Spotify con flujo OAuth (Authorization Code) y caché de token en disco.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        token_cache: Path,
        open_browser: bool,
    ) -> None:
        """
        @brief Crea el cliente y carga el token guardado, si existe.
        @param client_id     Client ID de la app en Spotify Developer.
        @param client_secret Client Secret de la app (no subir nunca al repositorio).
        @param redirect_uri  URI de redirección registrada (debe ser localhost).
        @param token_cache   Archivo JSON donde se guarda el token.
        @param open_browser  Si es True, abre el navegador automáticamente al autorizar.
        """
        ## Client ID de la aplicación.
        self.client_id = client_id
        ## Client Secret de la aplicación.
        self.client_secret = client_secret
        ## URI de redirección OAuth.
        self.redirect_uri = redirect_uri
        ## Ruta del archivo de caché del token.
        self.token_cache = token_cache
        ## Indica si se abre el navegador solo.
        self.open_browser = open_browser
        ## Token actual (access_token, refresh_token, expires_at...) o None.
        self.token = self._load_token()

    def get_currently_playing(self) -> dict[str, Any] | None:
        """
        @brief Consulta qué se está reproduciendo.

        Renueva el token si ha caducado (401) y espera si Spotify limita las peticiones (429).

        @return JSON de la respuesta, o None si no hay nada sonando o hubo límite de peticiones.
        @throws RuntimeError ante cualquier otro error HTTP.
        """
        token = self._valid_access_token()
        response = http_request(
            "GET",
            CURRENTLY_PLAYING_URL,
            params={"additional_types": "track,episode"},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )

        if response.status == 204:
            return None
        if response.status == 401:
            self._refresh_access_token()
            return self.get_currently_playing()
        if response.status == 429:
            retry_after = int(response.headers.get("Retry-After", "5"))
            time.sleep(max(retry_after, 1))
            return None
        if response.status != 200:
            raise_http_error(response, "Spotify currently-playing request")

        return response.json()

    def authorize(self) -> None:
        """@brief Fuerza la autorización (si hace falta) y deja el token en caché."""
        self._valid_access_token()

    def _valid_access_token(self) -> str:
        """
        @brief Devuelve un access token válido, autorizando o renovando si es necesario.
        @return Access token en texto.
        """
        if not self.token:
            self.token = self._authorize()

        if time.time() >= float(self.token.get("expires_at", 0)):
            self._refresh_access_token()

        return str(self.token["access_token"])

    def _load_token(self) -> dict[str, Any] | None:
        """
        @brief Lee el token del archivo de caché.
        @return Token como diccionario, o None si no existe el archivo.
        """
        if not self.token_cache.exists():
            return None

        with self.token_cache.open("r", encoding="utf-8") as token_file:
            return json.load(token_file)

    def _save_token(self, token: dict[str, Any]) -> None:
        """
        @brief Guarda el token en disco calculando su caducidad.

        Conserva el refresh_token anterior si la respuesta nueva no incluye uno.

        @param token Respuesta de Spotify con el token.
        """
        self.token_cache.parent.mkdir(parents=True, exist_ok=True)
        token["expires_at"] = time.time() + int(token.get("expires_in", 3600)) - 60

        previous_refresh_token = self.token.get("refresh_token") if self.token else None
        if previous_refresh_token and "refresh_token" not in token:
            token["refresh_token"] = previous_refresh_token

        with self.token_cache.open("w", encoding="utf-8") as token_file:
            json.dump(token, token_file, indent=2)

        self.token = token

    def _authorize(self) -> dict[str, Any]:
        """
        @brief Ejecuta el flujo OAuth completo con un servidor local para recibir el código.
        @return Token obtenido (ya guardado en caché).
        @throws RuntimeError si la URI de redirección no es localhost o la autorización falla.
        """
        state = secrets.token_urlsafe(18)
        parsed_redirect = urllib.parse.urlparse(self.redirect_uri)
        if parsed_redirect.hostname not in {"127.0.0.1", "localhost"}:
            raise RuntimeError("This script expects a localhost Spotify redirect URI.")

        callback = LocalCallbackServer(
            host=parsed_redirect.hostname or "127.0.0.1",
            port=parsed_redirect.port or 80,
            path=parsed_redirect.path or "/callback",
            expected_state=state,
        )

        query = urllib.parse.urlencode(
            {
                "client_id": self.client_id,
                "response_type": "code",
                "redirect_uri": self.redirect_uri,
                "scope": SCOPE,
                "state": state,
            }
        )
        auth_url = f"{AUTH_URL}?{query}"

        print("Authorize Spotify in your browser:")
        print(auth_url)
        if self.open_browser:
            webbrowser.open(auth_url)

        code = callback.wait_for_code()
        token = self._post_token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
            }
        )
        self._save_token(token)
        return token

    def _refresh_access_token(self) -> None:
        """@brief Renueva el access token con el refresh token (o reautoriza si no hay)."""
        refresh_token = self.token.get("refresh_token") if self.token else None
        if not refresh_token:
            self.token = self._authorize()
            return

        token = self._post_token(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }
        )
        self._save_token(token)

    def _post_token(self, data: dict[str, str]) -> dict[str, Any]:
        """
        @brief Pide un token al endpoint de Spotify usando autenticación Basic.
        @param data Campos del formulario (grant_type, code/refresh_token...).
        @return JSON con el token.
        @throws RuntimeError si Spotify responde con error.
        """
        credentials = f"{self.client_id}:{self.client_secret}".encode("utf-8")
        basic_auth = base64.b64encode(credentials).decode("ascii")
        response = http_request(
            "POST",
            TOKEN_URL,
            data=data,
            headers={
                "Authorization": f"Basic {basic_auth}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=10,
        )
        if response.status != 200:
            raise_http_error(response, "Spotify token request")
        return response.json()


class LocalCallbackServer:
    """
    @brief Servidor HTTP temporal que recibe el código de autorización de Spotify.
    """

    def __init__(self, host: str, port: int, path: str, expected_state: str) -> None:
        """
        @brief Abre el servidor en el host/puerto indicados.
        @param host           Dirección de escucha (127.0.0.1 o localhost).
        @param port           Puerto de escucha.
        @param path           Ruta de callback esperada (p. ej. /callback).
        @param expected_state Valor "state" que debe devolver Spotify (protección CSRF).
        """
        ## Código de autorización recibido (None hasta que llegue).
        self.code: str | None = None
        ## Error devuelto por Spotify, si lo hay.
        self.error: str | None = None
        ## Error si el parámetro "state" no coincide.
        self.state_error: str | None = None
        ## Ruta de callback esperada.
        self.path = path
        ## Valor "state" esperado.
        self.expected_state = expected_state

        parent = self

        class Handler(BaseHTTPRequestHandler):
            """@brief Manejador de la petición GET del callback."""

            def do_GET(self) -> None:
                """@brief Valida ruta y state, y extrae el código o el error."""
                parsed = urllib.parse.urlparse(self.path)
                params = urllib.parse.parse_qs(parsed.query)

                if parsed.path != parent.path:
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(b"Wrong callback path.")
                    return

                returned_state = params.get("state", [""])[0]
                if returned_state != parent.expected_state:
                    parent.state_error = "Spotify callback state did not match."
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"State mismatch.")
                    return

                if "error" in params:
                    parent.error = params["error"][0]
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"Spotify authorization failed.")
                    return

                parent.code = params.get("code", [None])[0]
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"Spotify authorization complete. You can close this tab.")

            def log_message(self, format: str, *args: Any) -> None:
                """@brief Silencia el log por consola del servidor."""
                return

        ## Servidor HTTP subyacente.
        self.server = HTTPServer((host, port), Handler)

    def wait_for_code(self) -> str:
        """
        @brief Bloquea hasta recibir el código de autorización y cierra el servidor.
        @return Código de autorización.
        @throws RuntimeError si hay error de state, error de Spotify o no llega código.
        """
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        try:
            while not self.code and not self.error and not self.state_error:
                time.sleep(0.1)
        finally:
            self.server.shutdown()
            self.server.server_close()

        if self.state_error:
            raise RuntimeError(self.state_error)
        if self.error:
            raise RuntimeError(f"Spotify authorization failed: {self.error}")
        if not self.code:
            raise RuntimeError("Spotify authorization did not return a code.")
        return self.code


def playback_art_from_response(playback: dict[str, Any] | None) -> PlaybackArt | None:
    """
    @brief Extrae la carátula de la respuesta de "reproduciendo ahora".
    @param playback JSON devuelto por Spotify (o None).
    @return PlaybackArt con la imagen más grande, o None si no hay carátula disponible.
    """
    if not playback:
        return None

    item = playback.get("item")
    if not item:
        return None

    if item.get("type") == "track":
        images = item.get("album", {}).get("images", [])
    else:
        images = item.get("images", [])

    if not images:
        return None

    image = max(images, key=lambda candidate: candidate.get("width") or 0)
    item_id = item.get("id") or item.get("uri") or image["url"]
    return PlaybackArt(
        key=str(item_id),
        image_url=image["url"],
        is_playing=bool(playback.get("is_playing")),
    )


def download_image(url: str) -> Image.Image:
    """
    @brief Descarga una imagen y la convierte a RGB.
    @param url URL de la imagen.
    @return Imagen PIL en modo RGB.
    """
    import requests

    response = requests.get(url, timeout=15)
    response.raise_for_status()
    return Image.open(BytesIO(response.content)).convert("RGB")


class SpotifyPoller:
    """
    @brief Consulta Spotify en un hilo aparte y guarda la última carátula.

    Cualquier escena (disco, modo automático, texto de "ahora suena"...) puede
    leer el estado con snapshot() sin duplicar peticiones.
    """

    def __init__(self, client: SpotifyClient, poll_seconds: float = 2.0) -> None:
        """
        @brief Prepara el sondeo (no arranca el hilo; ver start()).
        @param client       Cliente de Spotify ya configurado.
        @param poll_seconds Segundos entre consultas.
        """
        ## Cliente usado para consultar la API.
        self.client = client
        ## Intervalo entre consultas, en segundos.
        self.poll_seconds = poll_seconds
        ## Cerrojo que protege el estado compartido con el hilo de dibujo.
        self._lock = threading.Lock()
        ## Evento para pedir la parada del hilo.
        self._stop = threading.Event()
        ## Hilo de sondeo (None hasta llamar a start()).
        self._thread: threading.Thread | None = None
        ## Identificador de la canción actual.
        self._art_key: str | None = None
        ## URL de la carátula actual.
        self._image_url: str | None = None
        ## Carátula descargada, o None si no hay nada sonando.
        self._image: Image.Image | None = None
        ## True si hay reproducción en marcha.
        self._is_playing = False

    def start(self) -> None:
        """@brief Arranca el hilo de sondeo."""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """@brief Detiene el hilo de sondeo y espera (máx. 1 s) a que termine."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)

    def snapshot(self) -> tuple[Image.Image | None, bool]:
        """
        @brief Devuelve el estado actual de forma segura entre hilos.
        @return Tupla (carátula o None, True si está reproduciendo).
        """
        with self._lock:
            return self._image, self._is_playing

    def _run(self) -> None:
        """@brief Bucle del hilo: consulta Spotify, descarga carátulas nuevas y actualiza el estado."""
        last_status: str | None = None

        while not self._stop.is_set():
            try:
                art = playback_art_from_response(self.client.get_currently_playing())

                if art:
                    with self._lock:
                        needs_download = art.key != self._art_key or art.image_url != self._image_url

                    image = download_image(art.image_url) if needs_download else None

                    with self._lock:
                        self._art_key = art.key
                        self._image_url = art.image_url
                        self._is_playing = art.is_playing
                        if image is not None:
                            self._image = image

                    status = f"art found, is_playing={art.is_playing}"
                else:
                    with self._lock:
                        self._art_key = None
                        self._image_url = None
                        self._image = None
                        self._is_playing = False
                    status = "no currently playing item"

                if status != last_status:
                    print(f"Spotify: {status}", flush=True)
                    last_status = status
            except Exception as exc:
                print(f"Spotify poll failed: {exc}", flush=True)

            self._stop.wait(self.poll_seconds)
