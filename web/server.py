"""
@file server.py
@brief API REST (FastAPI) y servidor web de la interfaz para controlar la matriz.

La API es deliberadamente fina: toda la lógica vive en core.controller.Controller,
y aquí solo se traducen peticiones HTTP a llamadas a ese controlador.

@par Endpoints
| Método | Ruta                              | Qué hace                                         |
|--------|-----------------------------------|--------------------------------------------------|
| GET    | /                                 | Página de control (HTML)                         |
| GET    | /api/state                        | Escena activa, brillo y todas las escenas        |
| POST   | /api/scene                        | Cambia de escena. Cuerpo: {"name": "..."}        |
| POST   | /api/scenes/{name}/settings       | Cambia ajustes. Cuerpo: {"values": {...}}        |
| POST   | /api/brightness                   | Cambia el brillo. Cuerpo: {"value": 0-100}       |
| GET    | /api/preview.png                  | Último fotograma mostrado (PNG de 64x64)         |
| GET    | /docs                             | Documentación interactiva generada por FastAPI   |
"""
import socket
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from core.controller import Controller
from core.preview import FramePublisher

## Puerto en el que escucha la interfaz web.
WEB_PORT = 8000

## Carpeta con los archivos estáticos de la interfaz (HTML, JS, CSS).
STATIC_DIR = Path(__file__).parent / "static"


class SceneRequest(BaseModel):
    """@brief Cuerpo de POST /api/scene."""

    ## Identificador de la escena a activar.
    name: str


class SettingsRequest(BaseModel):
    """@brief Cuerpo de POST /api/scenes/{name}/settings."""

    ## Ajustes a modificar (clave -> valor). Se validan en Scene::configure.
    values: dict[str, Any]


class BrightnessRequest(BaseModel):
    """@brief Cuerpo de POST /api/brightness."""

    ## Brillo de 0 a 100.
    value: int = Field(ge=0, le=100)


def create_app(controller: Controller, publisher: FramePublisher) -> FastAPI:
    """
    @brief Construye la aplicación FastAPI.
    @param controller Controlador con el que se opera la matriz.
    @param publisher  Origen del fotograma para la vista previa en vivo.
    @return Aplicación FastAPI lista para servir con uvicorn.
    """
    app = FastAPI(title="Spotify Matrix", description="Control de la matriz LED")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        """@brief Devuelve la página de control."""
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/state")
    def get_state() -> dict[str, Any]:
        """@brief Devuelve el estado completo (escena activa, brillo, escenas y ajustes)."""
        return controller.state()

    @app.post("/api/scene")
    def post_scene(body: SceneRequest) -> dict[str, Any]:
        """
        @brief Cambia la escena activa.
        @param body    Cuerpo con el nombre de la escena.
        @return Estado actualizado.
        @throws HTTPException 404 si la escena no existe.
        """
        try:
            controller.set_scene(body.name)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Escena desconocida: {body.name}")
        return controller.state()

    @app.post("/api/scenes/{name}/settings")
    def post_settings(name: str, body: SettingsRequest) -> dict[str, Any]:
        """
        @brief Modifica ajustes de una escena (los valores no válidos se ignoran).
        @param name    Identificador de la escena.
        @param body    Cuerpo con los ajustes.
        @return Ajustes finales de la escena.
        @throws HTTPException 404 si la escena no existe.
        """
        try:
            return {"name": name, "settings": controller.configure(name, body.values)}
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Escena desconocida: {name}")

    @app.post("/api/brightness")
    def post_brightness(body: BrightnessRequest) -> dict[str, int]:
        """
        @brief Cambia el brillo de la matriz.
        @param body    Cuerpo con el valor (0 a 100).
        @return Brillo aplicado.
        """
        return {"brightness": controller.set_brightness(body.value)}

    @app.get("/api/preview.png")
    def get_preview() -> Response:
        """
        @brief Devuelve el último fotograma como PNG, sin caché del navegador.
        @throws HTTPException 503 si todavía no se ha dibujado ningún fotograma.
        """
        png = publisher.png()
        if png is None:
            raise HTTPException(status_code=503, detail="Todavía no hay fotogramas")
        return Response(content=png, media_type="image/png", headers={"Cache-Control": "no-store"})

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def local_urls(port: int = WEB_PORT) -> list[str]:
    """
    @brief Direcciones desde las que se puede abrir la interfaz en la red local.
    @param port Puerto del servidor.
    @return Lista con la URL por nombre de host (.local) y, si se detecta, por IP.
    """
    urls = [f"http://{socket.gethostname()}.local:{port}"]
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("10.255.255.255", 1))  # no envía nada: solo averigua qué interfaz se usaría
            urls.append(f"http://{sock.getsockname()[0]}:{port}")
    except OSError:
        pass
    return urls


class WebServer:
    """
    @brief Ejecuta uvicorn en un hilo en segundo plano, para que el bucle principal siga dibujando.
    """

    def __init__(self, app: FastAPI, port: int = WEB_PORT, host: str = "0.0.0.0") -> None:
        """
        @brief Prepara el servidor (no arranca; ver start()).
        @param app  Aplicación FastAPI.
        @param port Puerto de escucha.
        @param host Dirección de escucha (0.0.0.0 = accesible desde toda la red local).
        """
        import uvicorn

        ## Puerto de escucha.
        self.port = port
        ## Servidor uvicorn.
        self._server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
        ## Hilo donde corre el servidor.
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """@brief Arranca el servidor en un hilo demonio."""
        self._thread = threading.Thread(target=self._server.run, daemon=True, name="web-server")
        self._thread.start()

    def stop(self) -> None:
        """@brief Pide al servidor que se detenga y espera (máx. 2 s) a que termine."""
        self._server.should_exit = True
        if self._thread:
            self._thread.join(timeout=2)
