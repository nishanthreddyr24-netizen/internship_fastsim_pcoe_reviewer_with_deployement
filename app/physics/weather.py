"""Weather API wrapper with deterministic fallback behavior."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.error import URLError
from urllib.request import urlopen

from app.physics.schemas import Environment

DEFAULT_WEATHER = Environment(ambient_temp_c=25.0, wind_speed_kph=0.0, wind_direction_deg=0.0, precipitation_mm=0.0)
DEFAULT_TIMEOUT_S = 0.15


@dataclass(frozen=True)
class WeatherResult:
    environment: Environment
    elapsed_ms: float
    degraded: bool


def normalize_weather_payload(payload: dict) -> Environment:
    """Normalize common provider payload keys into the simulation environment schema."""
    current = payload.get("current") if isinstance(payload.get("current"), dict) else payload
    return Environment(
        ambient_temp_c=float(
            current.get("ambient_temp_c", current.get("temperature_2m", current.get("temp_c", 25.0))),
        ),
        wind_speed_kph=float(
            current.get("wind_speed_kph", current.get("wind_speed_10m", current.get("wind_kph", 0.0))),
        ),
        wind_direction_deg=float(
            current.get(
                "wind_direction_deg",
                current.get("wind_direction_10m", current.get("wind_degree", 0.0)),
            ),
        ),
        precipitation_mm=float(
            current.get("precipitation_mm", current.get("precipitation", current.get("precip_mm", 0.0))),
        ),
    )


def _default_fetcher(url: str, timeout_s: float) -> dict:
    with urlopen(url, timeout=timeout_s) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_weather(
    lat: float,
    lon: float,
    base_url: str | None = None,
    api_key: str | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    fetcher: Callable[[str, float], dict] | None = None,
) -> WeatherResult:
    """Fetch normalized weather and degrade to safe defaults on provider failure."""
    started = time.perf_counter()
    if base_url is None:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return WeatherResult(environment=DEFAULT_WEATHER, elapsed_ms=elapsed_ms, degraded=True)

    separator = "&" if "?" in base_url else "?"
    key_param = f"&appid={api_key}" if api_key else ""
    url = f"{base_url}{separator}lat={lat}&lon={lon}{key_param}"
    provider_fetcher = fetcher or _default_fetcher

    try:
        payload = provider_fetcher(url, timeout_s)
        environment = normalize_weather_payload(payload)
        degraded = False
    except (TimeoutError, URLError, OSError, ValueError, KeyError):
        environment = DEFAULT_WEATHER
        degraded = True

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    if elapsed_ms > timeout_s * 1000.0 and degraded:
        environment = DEFAULT_WEATHER
    return WeatherResult(environment=environment, elapsed_ms=elapsed_ms, degraded=degraded)
