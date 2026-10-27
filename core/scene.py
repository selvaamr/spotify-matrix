"""
@file scene.py
@brief Clase base de todas las escenas (modos) que puede mostrar la matriz.
"""

from __future__ import annotations
from typing import Any
from PIL import Image

class Scene:
    """
    @brief Clase base abstracta: todo lo que se puede ver en la matriz es una Scene.

    Para crear un modo nuevo basta con heredar de esta clase, sobrescribir
    update() y render(), y registrarlo en el SceneManager.

    @par Ejemplo de settings_schema
    @code
    settings_schema = {
        "rpm": {"type": "float", "min": 1, "max": 120, "default": 20, "label": "Velocidad"},
    }
    @endcode
    """

    ## Identificador único de la escena (se usa en la API y en los ajustes guardados).
    name = "base"

    ## Nombre legible que verá el usuario en la interfaz.
    label = "Base"

    ## Opciones que la escena expone al usuario; la interfaz web genera los controles a partir de aquí.
    settings_schema: dict[str, dict[str, Any]] = {}

    def __init__(self) -> None:
        """
        @brief Inicializa los ajustes actuales con los valores por defecto del esquema.
        """
        ## Valores actuales de los ajustes (clave -> valor).
        self.settings: dict[str, Any] = {
            key: spec["default"] for key, spec in self.settings_schema.items()
        }

    def configure(self, **values: Any) -> None:
        """
        @brief Actualiza ajustes de la escena.

        Las claves desconocidas se ignoran y los valores se limitan al rango
        "min"/"max" definido en settings_schema.

        @param values Pares clave=valor con los ajustes a modificar.
        """
        for key, value in values.items():
            spec = self.settings_schema.get(key)
            if spec is None:
                continue
            if "min" in spec:
                value = max(spec["min"], value)
            if "max" in spec:
                value = min(spec["max"], value)
            self.settings[key] = value

    def on_enter(self) -> None:
        """@brief Se invoca cuando la escena pasa a ser la activa."""

    def on_exit(self) -> None:
        """@brief Se invoca cuando la escena deja de ser la activa."""

    def update(self, dt: float) -> None:
        """
        @brief Avanza la lógica de la escena.
        @param dt Segundos transcurridos desde la llamada anterior.
        """

    def render(self, size: int) -> Image.Image:
        """
        @brief Dibuja el fotograma actual.
        @param size Lado en píxeles de la matriz (cuadrada).
        @return Imagen PIL de size x size píxeles.
        @throws NotImplementedError si la subclase no lo implementa.
        """
        raise NotImplementedError

    def on_input(self, event: dict[str, Any]) -> None:
        """
        @brief Recibe una entrada del usuario (mando táctil, botón físico...).
        @param event Diccionario con los datos del evento, p. ej. {"button": "up"}.
        """
