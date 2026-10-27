"""
@file http_utils.py
@brief Cliente HTTP mínimo basado en la librería estándar (urllib).
"""

from __future__ import annotations
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from email.message import Message
from typing import Any
from urllib.error import HTTPError

@dataclass
class HttpResponse:
    """
    @brief Respuesta HTTP simplificada.
    """

    ## Código de estado HTTP.
    status: int
    ## Cabeceras de la respuesta.
    headers: Message
    ## Cuerpo de la respuesta en bruto.
    body: bytes

    def json(self) -> dict[str, Any]:
        """
        @brief Decodifica el cuerpo como JSON.
        @return Diccionario con el contenido JSON.
        """
        return json.loads(self.body.decode("utf-8"))


def http_request(
    method: str,
    url: str,
    *,
    params: dict[str, str] | None = None,
    data: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 10,
) -> HttpResponse:
    """
    @brief Realiza una petición HTTP sin lanzar excepción en errores 4xx/5xx.

    @param method  Método HTTP ("GET", "POST"...).
    @param url     URL de destino.
    @param params  Parámetros de query string (opcional).
    @param data    Campos del cuerpo, codificados como formulario (opcional).
    @param headers Cabeceras adicionales (opcional).
    @param timeout Tiempo máximo de espera en segundos.
    @return Respuesta con estado, cabeceras y cuerpo.
    """
    if params:
        separator = "&" if urllib.parse.urlparse(url).query else "?"
        url = f"{url}{separator}{urllib.parse.urlencode(params)}"

    encoded_data = urllib.parse.urlencode(data).encode("utf-8") if data else None
    request = urllib.request.Request(
        url,
        data=encoded_data,
        headers=headers or {},
        method=method,
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return HttpResponse(response.status, response.headers, response.read())
    except HTTPError as exc:
        return HttpResponse(exc.code, exc.headers, exc.read())


def raise_http_error(response: HttpResponse, context: str) -> None:
    """
    @brief Lanza una excepción describiendo una respuesta HTTP fallida.
    @param response Respuesta recibida.
    @param context  Texto que indica qué petición falló.
    @throws RuntimeError siempre, con el código y el cuerpo de la respuesta.
    """
    body = response.body.decode("utf-8", errors="replace")
    raise RuntimeError(f"{context} failed with HTTP {response.status}: {body}")