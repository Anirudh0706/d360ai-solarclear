"""Weather forecast service.

External API: Open-Meteo (https://open-meteo.com) - free, no API key. Provides hourly
shortwave radiation (GHI), temperature and cloud cover. If the call fails, or
WEATHER_PROVIDER=clearsky, we fall back to a clear-sky model scaled by the site's
recent observed clearness, so forecasting never stops working offline.
"""
import logging
import sqlite3
from datetime import datetime, timedelta, timezone

import httpx

from app.analytics.solar import clearsky_ghi
from app.config import settings
from app.database import fetch_all, fetch_one

log = logging.getLogger("solarclear.weather")
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
TS_FMT = "%Y-%m-%dT%H:00"
REFRESH_HOURS = 3


def current_hour() -> datetime:
    return datetime.now().replace(minute=0, second=0, microsecond=0)


def fetch_open_meteo(lat: float, lon: float, start: datetime, hours: int) -> list[dict] | None:
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "shortwave_radiation,temperature_2m,cloud_cover",
        "forecast_days": 3,
        "timezone": "Asia/Kolkata",
    }
    try:
        resp = httpx.get(OPEN_METEO_URL, params=params, timeout=8)
        resp.raise_for_status()
        hourly = resp.json()["hourly"]
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        log.warning("Open-Meteo unavailable, using clear-sky model: %s", exc)
        return None
    start_key = start.strftime(TS_FMT)
    points = []
    for ts, ghi, temp, cloud in zip(
        hourly["time"], hourly["shortwave_radiation"], hourly["temperature_2m"], hourly["cloud_cover"]
    ):
        # Open-Meteo radiation is the mean of the preceding hour; shift to hour-start convention.
        hour_start = (datetime.fromisoformat(ts) - timedelta(hours=1)).strftime(TS_FMT)
        if hour_start >= start_key and ghi is not None:
            points.append({"ts": hour_start, "ghi_wm2": float(ghi), "temp_c": float(temp or 28),
                           "cloud_pct": float(cloud or 0), "source": "open-meteo"})
    return points[:hours] or None


def clearsky_forecast(conn: sqlite3.Connection, substation: dict, start: datetime, hours: int) -> list[dict]:
    """Clear-sky irradiance scaled by the median clearness index of the last 7 observed days."""
    observed = fetch_all(
        conn,
        "SELECT ts, ghi_wm2, temp_c FROM weather WHERE substation_id = ? AND kind = 'observed' "
        "ORDER BY ts DESC LIMIT 168",
        (substation["id"],),
    )
    ratios, temps = [], {}
    for row in observed:
        ts = datetime.fromisoformat(row["ts"])
        cs = clearsky_ghi(ts, substation["latitude"], substation["longitude"])
        if cs > 200:
            ratios.append(row["ghi_wm2"] / cs)
        temps.setdefault(ts.hour, []).append(row["temp_c"])
    clearness = sorted(ratios)[len(ratios) // 2] if ratios else 0.75
    points = []
    for i in range(hours):
        ts = start + timedelta(hours=i)
        hour_temps = temps.get(ts.hour) or [28.0]
        points.append({
            "ts": ts.strftime(TS_FMT),
            "ghi_wm2": round(clearsky_ghi(ts, substation["latitude"], substation["longitude"]) * clearness, 1),
            "temp_c": round(sum(hour_temps) / len(hour_temps), 1),
            "cloud_pct": round((1 - clearness) * 100, 1),
            "source": "clearsky-model",
        })
    return points


def get_forecast(conn: sqlite3.Connection, substation_id: int, hours: int = 48) -> list[dict]:
    """Return cached forecast for the next `hours`, refreshing it every few hours."""
    start = current_hour()
    end_key = (start + timedelta(hours=hours - 1)).strftime(TS_FMT)
    fresh = fetch_one(
        conn,
        "SELECT COUNT(*) AS n, MIN(fetched_at) AS oldest FROM weather "
        "WHERE substation_id = ? AND kind = 'forecast' AND ts BETWEEN ? AND ?",
        (substation_id, start.strftime(TS_FMT), end_key),
    )
    # fetched_at is stored by SQLite's datetime('now'), which is UTC.
    utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
    stale_before = (utc_now - timedelta(hours=REFRESH_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
    if not fresh or fresh["n"] < hours or fresh["oldest"] < stale_before:
        substation = fetch_one(conn, "SELECT * FROM substations WHERE id = ?", (substation_id,))
        points = None
        if settings.weather_provider == "open-meteo":
            points = fetch_open_meteo(substation["latitude"], substation["longitude"], start, hours)
        if not points or len(points) < hours:
            points = clearsky_forecast(conn, substation, start, hours)
        conn.executemany(
            "INSERT INTO weather (substation_id, ts, kind, ghi_wm2, temp_c, cloud_pct, source, fetched_at) "
            "VALUES (?, ?, 'forecast', ?, ?, ?, ?, datetime('now')) "
            "ON CONFLICT (substation_id, ts, kind) DO UPDATE SET ghi_wm2 = excluded.ghi_wm2, "
            "temp_c = excluded.temp_c, cloud_pct = excluded.cloud_pct, source = excluded.source, "
            "fetched_at = excluded.fetched_at",
            [(substation_id, p["ts"], p["ghi_wm2"], p["temp_c"], p["cloud_pct"], p["source"]) for p in points],
        )
    return fetch_all(
        conn,
        "SELECT ts, ghi_wm2, temp_c, cloud_pct, source FROM weather "
        "WHERE substation_id = ? AND kind = 'forecast' AND ts BETWEEN ? AND ? ORDER BY ts",
        (substation_id, start.strftime(TS_FMT), end_key),
    )
