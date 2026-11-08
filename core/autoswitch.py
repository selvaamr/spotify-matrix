"""
@file autoswitch.py
@brief Cambio automático al modo Spotify cuando empieza a sonar música, y vuelta al modo anterior al parar.

Reglas:
  -# Cuando Spotify empieza a reproducir, la matriz pasa al modo "Disco de Spotify" (si no estaba ya),
     recordando en qué modo estaba.
  -# Cuando deja de sonar durante unos segundos (para no saltar entre canción y canción), vuelve a ese
     modo anterior.
  -# Si mientras suena la música eliges otro modo a mano en la web, se respeta: al parar no se cambia nada.
  -# Si pusiste el modo Spotify a mano (no lo cambió esto), al parar se queda en él y muestra "PLAY SPOTIFY".

Solo actúa en los cambios de "suena" a "no suena" y al revés, así que nunca pelea con lo que eliges en la web.
"""
from __future__ import annotations

import time
from typing import Callable, Protocol

## Escena a la que se cambia cuando suena música.
SPOTIFY_SCENE = "spotify_record"

## Segundos sin música antes de volver al modo anterior (evita saltos entre canciones).
STOP_DELAY = 6.0

## Segundos entre comprobaciones (el estado de Spotify se consulta cada 2 s, no hace falta más).
CHECK_INTERVAL = 0.5


class _Controller(Protocol):
    """@brief Lo que necesita este módulo del controlador (ver core/controller.py)."""

    def state(self) -> dict: ...
    def set_scene(self, name: str) -> None: ...


class SpotifyAutoSwitch:
    """
    @brief Cambia al modo Spotify al empezar la música y vuelve al modo anterior al parar.
    """

    def __init__(
        self,
        controller: _Controller,
        is_playing: Callable[[], bool],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """
        @brief Prepara el cambio automático.
        @param controller Controlador con el que se cambia de modo.
        @param is_playing Función que dice si Spotify está reproduciendo ahora mismo.
        @param clock      Reloj en segundos (se puede sustituir en las pruebas).
        """
        ## Controlador de la matriz.
        self._controller = controller
        ## Consulta de si suena música.
        self._is_playing = is_playing
        ## Reloj.
        self._clock = clock
        ## Último estado visto (suena / no suena).
        self._playing = False
        ## Modo al que volver cuando pare la música, o None si no hay que volver a ninguno.
        self._return_to: str | None = None
        ## Momento en que dejó de sonar (None si está sonando o ya se ha vuelto).
        self._stopped_at: float | None = None
        ## Momento de la última comprobación.
        self._last_check = float("-inf")

    def _current(self) -> str:
        """@brief Modo activo ahora mismo."""
        return str(self._controller.state().get("scene", ""))

    def tick(self) -> None:
        """
        @brief Se llama en cada vuelta del bucle principal; comprueba el estado cada CHECK_INTERVAL segundos.
        """
        now = self._clock()
        if now - self._last_check < CHECK_INTERVAL:
            return
        self._last_check = now
        playing = bool(self._is_playing())

        if playing and not self._playing:
            # Empieza a sonar: se cambia a Spotify recordando el modo en el que estaba.
            self._stopped_at = None
            current = self._current()
            if self._return_to is None and current != SPOTIFY_SCENE:
                self._return_to = current
                self._set(SPOTIFY_SCENE)
        elif not playing and self._playing:
            self._stopped_at = now

        if playing and self._return_to is not None and self._current() != SPOTIFY_SCENE:
            # Se ha elegido otro modo a mano mientras sonaba: se respeta y ya no se vuelve a ningún sitio.
            self._return_to = None

        if not playing and self._stopped_at is not None and now - self._stopped_at >= STOP_DELAY:
            self._stopped_at = None
            if self._return_to is not None and self._current() == SPOTIFY_SCENE:
                self._set(self._return_to)
            self._return_to = None

        self._playing = playing

    def _set(self, name: str) -> None:
        """
        @brief Cambia de modo sin romper el programa si el modo ya no existe.
        @param name Identificador del modo.
        """
        try:
            self._controller.set_scene(name)
        except KeyError:
            pass
