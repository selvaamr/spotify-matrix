"""
@file controller.py
@brief Operaciones de alto nivel para controlar la matriz (la capa web solo las expone).

Reúne en un único sitio el gestor de escenas, la persistencia de ajustes y la pantalla.
Así la lógica se puede probar sin servidor web y cualquier otra interfaz futura
(botones físicos, otra app...) puede reutilizarla.
"""
from __future__ import annotations

from typing import Any

from core.display import DEFAULT_BRIGHTNESS
from core.manager import SceneManager
from core.scene import Scene
from core.settings import SettingsStore


class Controller:
    """
    @brief Fachada que coordina SceneManager, SettingsStore y la pantalla.
    """

    def __init__(
        self,
        manager: SceneManager,
        store: SettingsStore,
        display: Any,
        default_scene: str,
        default_brightness: int = DEFAULT_BRIGHTNESS,
    ) -> None:
        """
        @brief Crea el controlador.
        @param manager            Gestor de escenas con las escenas ya registradas.
        @param store              Almacén de ajustes persistentes.
        @param display            Pantalla (MatrixDisplay o MockDisplay); necesita set_brightness().
        @param default_scene      Escena que se activa si no hay ninguna guardada válida.
        @param default_brightness Brillo si no hay ninguno guardado.
        """
        ## Gestor de escenas.
        self.manager = manager
        ## Almacén de ajustes.
        self.store = store
        ## Pantalla.
        self.display = display
        ## Escena por defecto.
        self.default_scene = default_scene
        ## Brillo actual (0 a 100).
        self.brightness = default_brightness

    def restore(self) -> None:
        """
        @brief Aplica los ajustes guardados y activa la escena que había (o la de por defecto).

        Las escenas o ajustes guardados que ya no existan se ignoran.
        """
        for name in self.manager.names():
            saved = self.store.scene_settings(name)
            if saved:
                self.manager.configure(name, **saved)

        saved_scene = self.store.scene
        start = saved_scene if saved_scene in self.manager.names() else self.default_scene
        self.manager.set_scene(start)

        saved_brightness = self.store.brightness
        self.brightness = saved_brightness if saved_brightness is not None else self.brightness
        self.display.set_brightness(self.brightness)

    def state(self) -> dict[str, Any]:
        """
        @brief Estado completo para la interfaz: escena activa, brillo y todas las escenas con sus ajustes.
        @return Diccionario serializable a JSON.
        """
        return {
            "scene": self.manager.current_name,
            "brightness": self.brightness,
            "scenes": [self._describe(self.manager.get(name)) for name in self.manager.names()],
        }

    def set_scene(self, name: str) -> None:
        """
        @brief Cambia de escena y lo recuerda.
        @param name Identificador de la escena.
        @throws KeyError si la escena no existe.
        """
        self.manager.set_scene(name)
        self.store.set_scene(name)

    def configure(self, name: str, values: dict[str, Any]) -> dict[str, Any]:
        """
        @brief Modifica ajustes de una escena y los recuerda.

        Los valores se validan en Scene::configure (tipo, rango, opciones válidas).

        @param name   Identificador de la escena.
        @param values Pares clave -> valor.
        @return Ajustes finales de la escena (ya validados).
        @throws KeyError si la escena no existe.
        """
        self.manager.configure(name, **values)
        settings = dict(self.manager.get(name).settings)
        self.store.set_scene_settings(name, settings)
        return settings

    def set_brightness(self, value: int) -> int:
        """
        @brief Cambia el brillo de la matriz y lo recuerda.
        @param value Brillo de 0 a 100 (se limita a ese rango).
        @return Brillo aplicado.
        """
        self.brightness = max(0, min(100, int(value)))
        self.display.set_brightness(self.brightness)
        self.store.set_brightness(self.brightness)
        return self.brightness

    def shutdown(self) -> None:
        """@brief Fuerza el guardado pendiente de ajustes (llamar al cerrar el programa)."""
        self.store.flush()

    @staticmethod
    def _describe(scene: Scene) -> dict[str, Any]:
        """
        @brief Describe una escena para la interfaz.
        @param scene Escena a describir.
        @return Diccionario con name, label, settings actuales y schema (lista de controles).
        """
        return {
            "name": scene.name,
            "label": scene.label,
            "settings": dict(scene.settings),
            "schema": [{"key": key, **spec} for key, spec in scene.settings_schema.items()],
        }