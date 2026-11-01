"""
@file weather.py
@brief Consulta del tiempo con Open-Meteo (gratuito y sin clave de API) en un hilo aparte.

La ubicación se configura en el archivo .env (junto a main.py), con una de estas opciones:
@code
WEATHER_CITY=Villaviciosa de Odón     # se busca con el geocodificador de Open-Meteo
WEATHER_LAT=40.357                    # o las coordenadas exactas (tienen prioridad sobre la ciudad)
WEATHER_LON=-3.9
@endcode
Si no se indica nada se usa Madrid.

Si falla la conexión se conservan los últimos datos y se reintenta pronto. Si los datos tienen
más de tres horas se consideran caducados y la escena mostrará "SIN DATOS".
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass


## Endpoint de la previsión.
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
## Endpoint del buscador de ciudades.
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
## Latitud por defecto (Madrid).
DEFAULT_LATITUDE = 40.4168
## Longitud por defecto (Madrid).
DEFAULT_LONGITUDE = -3.7038
## Segundos entre consultas correctas.
REFRESH_SECONDS = 15 * 60
## Segundos hasta reintentar tras un fallo.
RETRY_SECONDS = 60
## Segundos tras los cuales los datos se consideran caducados.
MAX_AGE_SECONDS = 3 * 60 * 60


def _get_json(url: str, params: dict[str, str], context: str) -> dict:
    """
    @brief Hace una petición GET y devuelve el JSON de la respuesta (solo librería estándar).
    @param url     Dirección base de la API.
    @param params  Parámetros de la consulta.
    @param context Nombre del servicio, para los mensajes de error.
    @return Respuesta ya interpretada como diccionario.
    @throws RuntimeError si la red falla, la API responde con error o el JSON no es válido.
    """
    full_url = f"{url}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(full_url, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{context} failed with HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise RuntimeError(f"{context} failed: {exc}") from exc


@dataclass(frozen=True)
class DayForecast:
    """
    @brief Previsión de un día.
    """

    ## Fecha en formato AAAA-MM-DD, en la hora local del lugar.
    date: str
    ## Código meteorológico WMO.
    code: int
    ## Temperatura máxima en °C.
    tmax: float
    ## Temperatura mínima en °C.
    tmin: float


@dataclass(frozen=True)
class WeatherData:
    """
    @brief Tiempo actual y previsión de los próximos días.
    """

    ## Temperatura actual en °C.
    temp: float
    ## Código meteorológico WMO actual.
    code: int
    ## True si es de día en el lugar.
    is_day: bool
    ## Previsión por días; el primero es hoy.
    days: tuple[DayForecast, ...]


class WeatherPoller:
    """
    @brief Consulta Open-Meteo periódicamente y guarda el último resultado.
    """

    def __init__(self, latitude: float | None = None, longitude: float | None = None, city: str | None = None) -> None:
        """
        @brief Prepara el sondeo (no arranca el hilo; ver start()).
        @param latitude  Latitud, o None si se va a buscar por ciudad.
        @param longitude Longitud, o None si se va a buscar por ciudad.
        @param city      Nombre de la ciudad a buscar si no hay coordenadas.
        """
        ## Latitud en uso (None hasta resolver la ciudad).
        self.latitude = latitude
        ## Longitud en uso (None hasta resolver la ciudad).
        self.longitude = longitude
        ## Ciudad a buscar.
        self.city = city
        ## Cerrojo que protege el último resultado.
        self._lock = threading.Lock()
        ## Evento para pedir la parada del hilo.
        self._stop = threading.Event()
        ## Hilo de sondeo.
        self._thread: threading.Thread | None = None
        ## Último resultado correcto.
        self._data: WeatherData | None = None
        ## Instante (time.monotonic) del último resultado correcto.
        self._fetched_at = 0.0

    def start(self) -> None:
        """@brief Arranca el hilo de sondeo."""
        self._thread = threading.Thread(target=self._run, daemon=True, name="weather")
        self._thread.start()

    def stop(self) -> None:
        """@brief Detiene el hilo y espera (máx. 1 s) a que termine."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)

    def snapshot(self) -> WeatherData | None:
        """
        @brief Devuelve los últimos datos correctos, seguros entre hilos.
        @return Datos del tiempo, o None si aún no hay o están caducados.
        """
        with self._lock:
            if self._data is None or time.monotonic() - self._fetched_at > MAX_AGE_SECONDS:
                return None
            return self._data

    def fetch_once(self) -> WeatherData:
        """
        @brief Resuelve la ciudad si hace falta y descarga el tiempo.
        @return Datos del tiempo ya guardados como último resultado.
        @throws RuntimeError si la ciudad no existe, la API responde con error o el formato no es el esperado.
        """
        if self.latitude is None or self.longitude is None:
            self._geocode()
        data = self._download()
        with self._lock:
            self._data, self._fetched_at = data, time.monotonic()
        return data

    def _geocode(self) -> None:
        """
        @brief Busca las coordenadas de la ciudad configurada.
        @throws RuntimeError si no se encuentra la ciudad o la respuesta falla.
        """
        payload = _get_json(GEOCODING_URL, {"name": self.city or "", "count": "1", "language": "es"}, "Open-Meteo geocoding")
        results = payload.get("results") or []
        if not results:
            raise RuntimeError(f"Open-Meteo no encuentra la ciudad '{self.city}'. Revisa WEATHER_CITY en el .env.")
        self.latitude, self.longitude = float(results[0]["latitude"]), float(results[0]["longitude"])
        print(f"Tiempo: '{self.city}' -> {results[0].get('name', '?')} ({self.latitude:.3f}, {self.longitude:.3f})", flush=True)

    def _download(self) -> WeatherData:
        """
        @brief Descarga el tiempo actual y la previsión de tres días.
        @return Datos interpretados.
        @throws RuntimeError si la API responde con error o el formato no es el esperado.
        """
        payload = _get_json(
            FORECAST_URL,
            {
                "latitude": f"{self.latitude}",
                "longitude": f"{self.longitude}",
                "current": "temperature_2m,weather_code,is_day",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min",
                "timezone": "auto",
                "forecast_days": "3",
            },
            "Open-Meteo forecast",
        )
        return parse_forecast(payload)

    def _run(self) -> None:
        """@brief Bucle del hilo: descarga, espera y repite; ante un fallo avisa (una vez por mensaje) y reintenta pronto."""
        last_error: str | None = None
        while not self._stop.is_set():
            try:
                self.fetch_once()
                if last_error is not None:
                    print("Tiempo: conexión recuperada.", flush=True)
                last_error = None
                wait = REFRESH_SECONDS
            except Exception as exc:  # noqa: BLE001 - cualquier fallo de red o formato debe reintentarse
                message = str(exc)
                if message != last_error:
                    print(f"Tiempo: no se pudo actualizar ({message}). Se reintenta cada {RETRY_SECONDS} s.", flush=True)
                    last_error = message
                wait = RETRY_SECONDS
            self._stop.wait(wait)


def parse_forecast(payload: dict) -> WeatherData:
    """
    @brief Interpreta la respuesta JSON de Open-Meteo.
    @param payload JSON ya decodificado.
    @return Datos del tiempo.
    @throws RuntimeError si falta algún campo o tiene un tipo inesperado.
    """
    try:
        current = payload["current"]
        daily = payload["daily"]
        days = tuple(
            DayForecast(str(date), int(code), float(tmax), float(tmin))
            for date, code, tmax, tmin in zip(
                daily["time"], daily["weather_code"], daily["temperature_2m_max"], daily["temperature_2m_min"]
            )
        )
        if not days:
            raise ValueError("sin días")
        return WeatherData(float(current["temperature_2m"]), int(current["weather_code"]), bool(current["is_day"]), days)
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"Respuesta de Open-Meteo inesperada ({exc!r})") from exc


def poller_from_env() -> WeatherPoller:
    """
    @brief Crea el sondeo con la ubicación configurada en las variables de entorno (.env).

    Prioridad: WEATHER_LAT y WEATHER_LON, luego WEATHER_CITY y, si no hay nada, Madrid.

    @return Sondeo sin arrancar.
    """
    lat, lon, city = os.environ.get("WEATHER_LAT"), os.environ.get("WEATHER_LON"), os.environ.get("WEATHER_CITY")
    if lat and lon:
        try:
            return WeatherPoller(float(lat), float(lon))
        except ValueError:
            print("Tiempo: WEATHER_LAT/WEATHER_LON no son números; se ignoran.", flush=True)
    if city:
        return WeatherPoller(city=city)
    return WeatherPoller(DEFAULT_LATITUDE, DEFAULT_LONGITUDE)
