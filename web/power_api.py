"""
@file power_api.py
@brief API REST para apagar la Raspberry Pi desde la web (botón OFF de la página principal).

Se monta sobre la aplicación principal con app.include_router(), así server.py no cambia.

La petición no apaga directamente: avisa a main.py, que sale del bucle, guarda los ajustes,
apaga los LEDs y entonces apaga el sistema (ver power_off_system()).

@par Endpoints
| Método | Ruta            | Qué hace                                  |
|--------|-----------------|-------------------------------------------|
| POST   | /api/power/off  | Apaga la Raspberry Pi. Cuerpo: {"confirm": true} |
"""
import os
import shutil
import subprocess
from typing import Any, Callable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class PowerOffRequest(BaseModel):
    """@brief Cuerpo de POST /api/power/off (confirmación explícita, para evitar apagados por error)."""

    ## Debe ser true.
    confirm: bool = False


def create_power_router(request_power_off: Callable[[], None]) -> APIRouter:
    """
    @brief Construye el router con la ruta de apagado.
    @param request_power_off Función que pide al programa principal que se apague.
    @return Router de FastAPI listo para incluir en la aplicación.
    """
    router = APIRouter()

    @router.post("/api/power/off")
    def power_off(body: PowerOffRequest) -> dict[str, Any]:
        """
        @brief Pide el apagado de la Raspberry Pi.
        @param body Debe llevar {"confirm": true}.
        @return {"ok": true}
        @throws HTTPException 400 si falta la confirmación.
        """
        if not body.confirm:
            raise HTTPException(status_code=400, detail="Falta confirmar el apagado.")
        request_power_off()
        return {"ok": True}

    return router


def power_off_system() -> None:
    """
    @brief Apaga el sistema operativo de forma segura.

    El programa normalmente corre como root (sudo), y entonces basta con "systemctl poweroff".
    Si no es root, se intenta con "sudo -n" (solo funciona si sudo no pide contraseña).
    """
    command = ["systemctl", "poweroff"] if shutil.which("systemctl") else ["shutdown", "-h", "now"]
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        command = ["sudo", "-n", *command]
    print("Apagando la Raspberry Pi...", flush=True)
    try:
        subprocess.run(command, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"No se pudo apagar el sistema ({exc}). ¿Se está ejecutando con sudo?", flush=True)
