"""Physics helpers: sun position, clear-sky irradiance and PV output (no external libraries)."""
import math
from datetime import datetime

IST_MERIDIAN = 82.5  # standard meridian for Indian Standard Time


def solar_elevation_sin(ts: datetime, lat: float, lon: float) -> float:
    """Sine of the sun's elevation at the middle of the hour starting at `ts` (local IST)."""
    doy = ts.timetuple().tm_yday
    decl = math.radians(23.45 * math.sin(math.radians(360 / 365 * (284 + doy))))
    b = math.radians(360 / 365 * (doy - 81))
    equation_of_time = 9.87 * math.sin(2 * b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)
    clock_hour = ts.hour + ts.minute / 60 + 0.5
    solar_time = clock_hour + (4 * (lon - IST_MERIDIAN) + equation_of_time) / 60
    hour_angle = math.radians(15 * (solar_time - 12))
    phi = math.radians(lat)
    return math.sin(phi) * math.sin(decl) + math.cos(phi) * math.cos(decl) * math.cos(hour_angle)


def clearsky_ghi(ts: datetime, lat: float, lon: float) -> float:
    """Haurwitz clear-sky global horizontal irradiance in W/m2."""
    s = solar_elevation_sin(ts, lat, lon)
    if s <= 0.01:
        return 0.0
    return 1098 * s * math.exp(-0.057 / s)


def cell_temperature_derate(ghi: float, ambient_c: float) -> float:
    """Crystalline-Si temperature derating: -0.4 %/degC above 25 degC cell temperature."""
    cell_c = ambient_c + ghi / 800 * 25
    return 1 - 0.004 * (cell_c - 25)


def pv_output_kw(pv_kw: float, ghi: float, ambient_c: float, performance_ratio: float) -> float:
    if pv_kw <= 0 or ghi <= 0:
        return 0.0
    return max(0.0, pv_kw * ghi / 1000 * performance_ratio * cell_temperature_derate(ghi, ambient_c))


def percentile(values: list[float], pct: float) -> float:
    """Linear-interpolated percentile (pct in 0..100)."""
    if not values:
        return 0.0
    data = sorted(values)
    k = (len(data) - 1) * pct / 100
    lo, hi = math.floor(k), math.ceil(k)
    return data[lo] + (data[hi] - data[lo]) * (k - lo)


def linear_fit(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    """Ordinary least squares y = a + b*x. Returns (a, b, r2)."""
    n = len(xs)
    if n < 3:
        return (sum(ys) / n if n else 1.0), 0.0, 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return my, 0.0, 0.0
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    b = sxy / sxx
    a = my - b * mx
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys))
    r2 = 1 - ss_res / ss_tot if ss_tot else 0.0
    return a, b, r2
