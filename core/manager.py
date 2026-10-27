"""
@file manager.py
@brief Gestor que decide qué escena está activa y la actualiza/dibuja.
"""
from __future__ import annotations

import threading
from PIL import Image
from core.scene import Scene

class SceneManager:
    """
    @brief Registro de escenas y control de la escena activa.

    Es seguro usarlo desde varios hilos: el bucle de dibujo y el servidor web
    comparten la misma instancia, protegida con un RLock.
    """

    def __init__(self) -> None:
        """@brief Crea un gestor vacío, sin escena activa."""
        ## Escenas registradas (nombre -> instancia).
        self._scenes: dict[str, Scene] = {}
        ## Escena activa actualmente (None si aún no se ha elegido ninguna).
        self._current: Scene | None = None
        ## Cerrojo reentrante que protege el estado compartido entre hilos.
        self._lock = threading.RLock()

    def register(self, scene: Scene) -> None:
        """
        @brief Registra una escena para poder activarla por su nombre.
        @param scene Instancia de la escena (se indexa por Scene::name).
        """
        with self._lock:
            self._scenes[scene.name] = scene

    def names(self) -> list[str]:
        """
        @brief Lista los nombres de las escenas registradas.
        @return Lista de identificadores de escena.
        """
        return list(self._scenes)

    @property
    def current(self) -> Scene | None:
        """@brief Escena activa, o None si no hay ninguna."""
        return self._current

    def set_scene(self, name: str) -> None:
        """
        @brief Cambia la escena activa, llamando a on_exit() y on_enter().
        @param name Identificador de una escena ya registrada.
        @throws KeyError si no existe ninguna escena con ese nombre.
        """
        with self._lock:
            if name not in self._scenes:
                raise KeyError(f"Unknown scene: {name}")
            if self._current is not None:
                self._current.on_exit()
            self._current = self._scenes[name]
            self._current.on_enter()

    def update(self, dt: float) -> None:
        """
        @brief Avanza la lógica de la escena activa.
        @param dt Segundos desde el fotograma anterior.
        """
        with self._lock:
            if self._current:
                self._current.update(dt)

    def render(self, size: int) -> Image.Image:
        """
        @brief Dibuja la escena activa.
        @param size Lado en píxeles de la matriz.
        @return Fotograma de la escena, o una imagen negra si no hay escena activa.
        """
        with self._lock:
            if self._current is None:
                return Image.new("RGB", (size, size), (0, 0, 0))
            return self._current.render(size)

    def send_input(self, event: dict) -> None:
        """
        @brief Reenvía un evento de entrada a la escena activa.
        @param event Datos del evento (ver Scene::on_input).
        """
        with self._lock:
            if self._current:
                self._current.on_input(event)
