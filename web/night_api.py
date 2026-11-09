"""
@file night_api.py
@brief API REST del modo noche.

Se monta sobre la aplicación principal con app.include_router(), así server.py no cambia.

@par Endpoints
| Método | Ruta                 | Qué hace                                                            |
|--------|----------------------|---------------------------------------------------------------------|
| GET    | /api/night           | Estado: {"active", "auto", "start", "end"}                          |
| POST   | /api/night           | Enciende o apaga a mano. Cuerpo: {"active": true}                   |
| PUT    | /api/night/schedule  | Cambia el horario. Cuerpo: {"auto": true, "start": "22:00", "end": "08:00"} |
| PUT    | /api/night/level     | Intensidad del rojo (5 a 100). Cuerpo: {"level": 40}                |
"""
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.nightmode import NightMode


class NightRequest(BaseModel):
    """@brief Cuerpo de POST /api/night."""

    ## True para encender el modo noche, False para apagarlo.
    active: bool


class LevelRequest(BaseModel):
    """@brief Cuerpo de PUT /api/night/level."""

    ## Intensidad del rojo en modo noche (se limita entre 5 y 100).
    level: int


class ScheduleRequest(BaseModel):
    """@brief Cuerpo de PUT /api/night/schedule."""

    ## Si se activa solo a las horas indicadas.
    auto: bool = True
    ## Hora de inicio (HH:MM).
    start: str = "22:00"
    ## Hora de fin (HH:MM).
    end: str = "08:00"


def create_night_router(night: NightMode) -> APIRouter:
    """
    @brief Construye el router con las rutas del modo noche.
    @param night Modo noche.
    @return Router de FastAPI listo para incluir en la aplicación.
    """
    router = APIRouter()

    @router.get("/api/night")
    def get_night() -> dict[str, Any]:
        """@brief Devuelve el estado del modo noche."""
        return night.state()

    @router.post("/api/night")
    def post_night(body: NightRequest) -> dict[str, Any]:
        """
        @brief Enciende o apaga el modo noche a mano (hasta la siguiente hora programada).
        @param body Estado deseado.
        @return Estado actualizado.
        """
        night.set_active(body.active)
        return night.state()

    @router.put("/api/night/schedule")
    def put_schedule(body: ScheduleRequest) -> dict[str, Any]:
        """
        @brief Cambia el horario automático.
        @param body Horario.
        @return Estado actualizado.
        @throws HTTPException 400 si alguna hora no es válida.
        """
        try:
            night.set_schedule(body.auto, body.start, body.end)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return night.state()

    @router.put("/api/night/level")
    def put_level(body: LevelRequest) -> dict[str, Any]:
        """
        @brief Cambia la intensidad del rojo en modo noche.
        @param body Intensidad.
        @return Estado actualizado.
        """
        night.set_level(body.level)
        return night.state()

    return router
