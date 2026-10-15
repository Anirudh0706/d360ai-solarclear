"""Core grid analytics: solar / net-export forecasting, hosting capacity, risk detection,
saturation flagging and net-meter feasibility clearance.

Everything here is deterministic Python driven by meter + weather data. The LLM agent
calls these functions as tools; it never invents numbers.

Model per DTR (learned from its own history):
  * PR       - performance ratio of installed PV, calibrated from metered solar vs irradiance
  * g        - planning peak generation per kW of PV (98th percentile of clear-day output)
  * L_min    - minimum midday load (10th percentile, 10:00-14:59) -> worst case for export
  * V = a + b * export_kw   - voltage sensitivity fitted by least squares on metered data

Hosting capacity (additional PV the DTR can absorb) = min of:
  reverse flow : (REVERSE_FLOW_LIMIT_PCT * kVA + L_min) / g - existing PV
  voltage      : ((VOLTAGE_UPPER_PU - a) / b + L_min) / g - existing PV
  policy cap   : POLICY_CAP_PCT * kVA - existing PV
"""
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime

from app.analytics.solar import linear_fit, percentile, pv_output_kw
from app.config import settings
from app.database import fetch_all, fetch_one
from app.services.weather import get_forecast

HISTORY_HOURS = 336  # 14 days of hourly readings
OPEN_STATUSES = ("pending", "evaluated")


@dataclass
class DtrModel:
    ctx: dict
    pr: float
    peak_factor: float
    min_day_load_kw: float
    load_by_hour: dict = field(default_factory=dict)
    v_a: float = 1.0
    v_b: float = 0.0
    v_r2: float = 0.0
    samples: int = 0


def dtr_context(conn: sqlite3.Connection, dtr_id: int) -> dict | None:
    return fetch_one(
        conn,
        """
        SELECT d.id, d.code, d.name, d.rating_kva, d.area_type, d.feeder_id,
               f.code AS feeder_code, f.rating_kva AS feeder_rating_kva, f.substation_id,
               s.latitude, s.longitude,
               COALESCE((SELECT SUM(pv_kw) FROM consumers c WHERE c.dtr_id = d.id), 0) AS pv_kw,
               COALESCE((SELECT SUM(pv_kw) FROM consumers c WHERE c.dtr_id = d.id AND c.scheme = 'kusum'), 0) AS kusum_kw,
               (SELECT COUNT(*) FROM consumers c WHERE c.dtr_id = d.id) AS consumers
        FROM dtrs d
        JOIN feeders f ON f.id = d.feeder_id
        JOIN substations s ON s.id = f.substation_id
        WHERE d.id = ?
        """,
        (dtr_id,),
    )


def build_model(conn: sqlite3.Connection, dtr_id: int) -> DtrModel | None:
    ctx = dtr_context(conn, dtr_id)
    if not ctx:
        return None
    history = fetch_all(
        conn,
        """
        SELECT r.ts, r.load_kw, r.solar_kw, r.net_kw, r.voltage_pu, w.ghi_wm2, w.temp_c
        FROM readings r
        LEFT JOIN weather w ON w.substation_id = ? AND w.kind = 'observed' AND w.ts = r.ts
        WHERE r.dtr_id = ? ORDER BY r.ts DESC LIMIT ?
        """,
        (ctx["substation_id"], dtr_id, HISTORY_HOURS),
    )
    pv = ctx["pv_kw"]

    # 1. Performance ratio: metered solar / ideal output, on bright hours only.
    ratios = [
        r["solar_kw"] / pv_output_kw(pv, r["ghi_wm2"], r["temp_c"], 1.0)
        for r in history
        if pv > 0 and r["ghi_wm2"] and r["ghi_wm2"] > 300 and r["solar_kw"] > 0
    ]
    pr = min(0.95, max(0.5, percentile(ratios, 50))) if len(ratios) >= 12 else settings.performance_ratio

    # 2. Planning peak output per kW installed (bright-day noon).
    unit_output = [pv_output_kw(1.0, r["ghi_wm2"], r["temp_c"], pr) for r in history if r["ghi_wm2"]]
    peak = min(0.95, max(0.5, percentile(unit_output, 98))) if unit_output else 0.8

    # 3. Load: hourly profile from the last 7 days, and minimum midday load.
    by_hour: dict[int, list[float]] = {}
    for r in history[:168]:
        by_hour.setdefault(int(r["ts"][11:13]), []).append(r["load_kw"])
    load_by_hour = {h: sum(v) / len(v) for h, v in by_hour.items()}
    midday = [r["load_kw"] for r in history if 10 <= int(r["ts"][11:13]) <= 14]
    min_day_load = percentile(midday, 10) if midday else 0.2 * ctx["rating_kva"]

    # 4. Voltage sensitivity: V = a + b * export.
    xs = [-r["net_kw"] for r in history]
    ys = [r["voltage_pu"] for r in history]
    a, b, r2 = linear_fit(xs, ys) if len(xs) >= 24 else (1.02, 0.0, 0.0)
    if b <= 1e-6:  # not enough export/voltage spread to learn from: use a typical LV value
        b = 0.1 / ctx["rating_kva"]

    return DtrModel(ctx, pr, peak, min_day_load, load_by_hour, a, b, r2, len(history))


def _pending_kw(conn: sqlite3.Connection, dtr_id: int, before_app_id: int | None = None) -> float:
    sql = "SELECT COALESCE(SUM(requested_kw), 0) AS kw FROM applications WHERE dtr_id = ? AND status IN (?, ?)"
    params: tuple = (dtr_id, *OPEN_STATUSES)
    if before_app_id is not None:
        sql += " AND id < ?"
        params += (before_app_id,)
    return fetch_one(conn, sql, params)["kw"]


def _growth_kw_per_month(conn: sqlite3.Connection, dtr_id: int) -> float:
    row = fetch_one(
        conn,
        "SELECT COALESCE(SUM(pv_kw), 0) AS kw FROM consumers "
        "WHERE dtr_id = ? AND pv_kw > 0 AND pv_commissioned_on >= date('now', '-365 days')",
        (dtr_id,),
    )
    return row["kw"] / 12


def hosting_capacity(conn: sqlite3.Connection, dtr_id: int, model: DtrModel | None = None) -> dict | None:
    m = model or build_model(conn, dtr_id)
    if not m:
        return None
    rating, pv, g, lmin = m.ctx["rating_kva"], m.ctx["pv_kw"], m.peak_factor, m.min_day_load_kw
    rev_limit_kw = rating * settings.reverse_flow_limit_pct / 100

    limits = {
        "reverse_flow": (rev_limit_kw + lmin) / g - pv,
        "voltage": ((settings.voltage_upper_pu - m.v_a) / m.v_b + lmin) / g - pv,
        "policy_cap": rating * settings.policy_cap_pct / 100 - pv,
    }
    binding = min(limits, key=limits.get)
    hosting = max(0.0, limits[binding])
    total = pv + hosting
    utilisation = pv / total if total > 0 else 1.0

    worst_export = pv * g - lmin
    pending = _pending_kw(conn, dtr_id)
    growth = _growth_kw_per_month(conn, dtr_id)
    months_left = hosting / growth if growth > 0 else None

    if hosting <= max(3.0, 0.03 * rating) or utilisation >= 0.9:
        status = "saturated"
    elif utilisation >= 0.7 or pending >= hosting or (months_left is not None and months_left <= 12):
        status = "watch"
    else:
        status = "available"

    return {
        "dtr_id": m.ctx["id"],
        "dtr_code": m.ctx["code"],
        "dtr_name": m.ctx["name"],
        "feeder_id": m.ctx["feeder_id"],
        "feeder_code": m.ctx["feeder_code"],
        "area_type": m.ctx["area_type"],
        "rating_kva": rating,
        "consumers": m.ctx["consumers"],
        "existing_pv_kw": round(pv, 1),
        "kusum_pv_kw": round(m.ctx["kusum_kw"], 1),
        "hosting_kw": round(hosting, 1),
        "total_capacity_kw": round(total, 1),
        "utilisation_pct": round(utilisation * 100, 1),
        "binding_constraint": binding,
        "limits_kw": {k: round(max(v, 0.0), 1) for k, v in limits.items()},
        "pending_kw": round(pending, 1),
        "headroom_after_queue_kw": round(hosting - pending, 1),
        "growth_kw_per_month": round(growth, 2),
        "months_to_saturation": round(months_left, 1) if months_left is not None else None,
        "status": status,
        "worst_case_now": {
            "export_kw": round(worst_export, 1),
            "voltage_pu": round(m.v_a + m.v_b * worst_export, 3),
            "reverse_flow_pct_of_rating": round(max(worst_export, 0) / rating * 100, 1),
        },
        "model": {
            "performance_ratio": round(m.pr, 3),
            "peak_gen_per_kw": round(g, 3),
            "min_midday_load_kw": round(lmin, 1),
            "voltage_intercept_pu": round(m.v_a, 4),
            "voltage_sensitivity_pu_per_kw": round(m.v_b, 5),
            "voltage_fit_r2": round(m.v_r2, 3),
            "samples": m.samples,
        },
    }


def network_hosting(conn: sqlite3.Connection, feeder_id: int | None = None) -> dict:
    """Hosting capacity for every DTR plus a feeder-level roll-up with its own reverse-flow limit."""
    sql = "SELECT id FROM dtrs" + (" WHERE feeder_id = ?" if feeder_id else "") + " ORDER BY code"
    dtr_ids = [r["id"] for r in fetch_all(conn, sql, (feeder_id,) if feeder_id else ())]
    dtrs, models = [], {}
    for dtr_id in dtr_ids:
        models[dtr_id] = build_model(conn, dtr_id)
        dtrs.append(hosting_capacity(conn, dtr_id, models[dtr_id]))

    feeders = []
    feeder_sql = "SELECT id, code, name, rating_kva FROM feeders" + (" WHERE id = ?" if feeder_id else "")
    for f in fetch_all(conn, feeder_sql + " ORDER BY code", (feeder_id,) if feeder_id else ()):
        members = [d for d in dtrs if d["feeder_id"] == f["id"]]
        pv = sum(d["existing_pv_kw"] for d in members)
        dtr_sum = sum(d["hosting_kw"] for d in members)
        lmin = sum(models[d["dtr_id"]].min_day_load_kw for d in members)
        g = sum(models[d["dtr_id"]].peak_factor for d in members) / len(members) if members else 0.8
        feeder_rev = (f["rating_kva"] * settings.reverse_flow_limit_pct / 100 + lmin) / g - pv
        hosting = max(0.0, min(dtr_sum, feeder_rev))
        feeders.append({
            "feeder_id": f["id"], "feeder_code": f["code"], "feeder_name": f["name"],
            "rating_kva": f["rating_kva"], "dtrs": len(members),
            "existing_pv_kw": round(pv, 1), "hosting_kw": round(hosting, 1),
            "binding_constraint": "feeder_reverse_flow" if feeder_rev < dtr_sum else "sum_of_dtrs",
            "saturated_dtrs": sum(1 for d in members if d["status"] == "saturated"),
            "watch_dtrs": sum(1 for d in members if d["status"] == "watch"),
        })
    return {"dtrs": dtrs, "feeders": feeders}


def forecast_dtr(conn: sqlite3.Connection, dtr_id: int, hours: int = 48, model: DtrModel | None = None) -> dict | None:
    """Hour-by-hour solar, load, net export and voltage forecast with risk flags."""
    m = model or build_model(conn, dtr_id)
    if not m:
        return None
    hours = max(1, min(hours, 72))
    pv, rating = m.ctx["pv_kw"], m.ctx["rating_kva"]
    rev_limit_kw = rating * settings.reverse_flow_limit_pct / 100
    weather = get_forecast(conn, m.ctx["substation_id"], hours)
    fallback_load = sum(m.load_by_hour.values()) / len(m.load_by_hour) if m.load_by_hour else 0.3 * rating

    points = []
    for w in weather:
        hour = int(w["ts"][11:13])
        solar = pv_output_kw(pv, w["ghi_wm2"], w["temp_c"], m.pr)
        load = m.load_by_hour.get(hour, fallback_load)
        export = solar - load
        voltage = m.v_a + m.v_b * export
        risks = []
        if voltage > settings.voltage_upper_pu:
            risks.append("overvoltage")
        if export > rev_limit_kw:
            risks.append("reverse_flow")
        points.append({
            "ts": w["ts"], "ghi_wm2": round(w["ghi_wm2"]), "solar_kw": round(solar, 1),
            "load_kw": round(load, 1), "net_export_kw": round(export, 1),
            "voltage_pu": round(voltage, 3), "risks": risks,
        })

    return {
        "dtr_id": dtr_id,
        "dtr_code": m.ctx["code"],
        "weather_source": weather[0]["source"] if weather else "none",
        "limits": {"voltage_upper_pu": settings.voltage_upper_pu, "reverse_flow_kw": round(rev_limit_kw, 1)},
        "summary": {
            "solar_energy_kwh": round(sum(p["solar_kw"] for p in points), 1),
            "export_energy_kwh": round(sum(max(p["net_export_kw"], 0) for p in points), 1),
            "peak_solar_kw": max((p["solar_kw"] for p in points), default=0),
            "peak_export_kw": max((p["net_export_kw"] for p in points), default=0),
            "max_voltage_pu": max((p["voltage_pu"] for p in points), default=0),
            "risk_hours": sum(1 for p in points if p["risks"]),
        },
        "points": points,
    }


def detect_risks(conn: sqlite3.Connection, feeder_id: int | None = None, hours: int = 48) -> list[dict]:
    """Forecast overvoltage / reverse-flow events, one event per DTR and risk type."""
    sql = "SELECT id FROM dtrs" + (" WHERE feeder_id = ?" if feeder_id else "") + " ORDER BY code"
    events = []
    for row in fetch_all(conn, sql, (feeder_id,) if feeder_id else ()):
        fc = forecast_dtr(conn, row["id"], hours)
        rating = dtr_context(conn, row["id"])["rating_kva"]
        for risk in ("overvoltage", "reverse_flow"):
            hits = [p for p in fc["points"] if risk in p["risks"]]
            if not hits:
                continue
            if risk == "overvoltage":
                peak = max(p["voltage_pu"] for p in hits)
                severe = peak >= settings.voltage_upper_pu + 0.02
                detail = f"voltage up to {peak:.3f} pu (limit {settings.voltage_upper_pu})"
            else:
                peak = max(p["net_export_kw"] for p in hits)
                severe = peak >= rating
                detail = f"reverse flow up to {peak:.0f} kW ({peak / rating * 100:.0f}% of {rating:.0f} kVA)"
            events.append({
                "dtr_id": row["id"], "dtr_code": fc["dtr_code"], "risk": risk,
                "severity": "critical" if severe else "warning",
                "first_at": hits[0]["ts"], "hours": len(hits), "peak": round(peak, 3), "detail": detail,
            })
    events.sort(key=lambda e: (e["severity"] != "critical", e["first_at"]))
    return events


def evaluate_request(
    conn: sqlite3.Connection, dtr_id: int, requested_kw: float, scheme: str = "rooftop", app_id: int | None = None
) -> dict | None:
    """Data-driven net-meter / KUSUM technical feasibility clearance (first-come-first-served queue)."""
    hc = hosting_capacity(conn, dtr_id)
    if not hc:
        return None
    queued = _pending_kw(conn, dtr_id, app_id) if app_id is not None else hc["pending_kw"]
    headroom = hc["hosting_kw"] - queued
    constraint = hc["binding_constraint"]

    if scheme == "kusum":
        # KUSUM plants are larger; the 11 kV feeder must also absorb them.
        feeder = network_hosting(conn, hc["feeder_id"])["feeders"][0]
        if feeder["hosting_kw"] < headroom:
            headroom, constraint = feeder["hosting_kw"], feeder["binding_constraint"]

    headroom = max(0.0, headroom)
    labels = {"reverse_flow": "reverse power flow", "voltage": "voltage rise", "policy_cap": "regulatory DTR cap",
              "feeder_reverse_flow": "11 kV feeder reverse flow", "sum_of_dtrs": "DTR limits on the feeder"}
    basis = (f"{hc['dtr_code']} ({hc['rating_kva']:.0f} kVA) has {hc['existing_pv_kw']} kW PV installed, "
             f"hosting capacity {hc['hosting_kw']} kW limited by {labels.get(constraint, constraint)}, "
             f"{queued:.1f} kW already queued ahead.")

    if requested_kw <= headroom:
        rec, rec_kw = "clear", requested_kw
        reason = f"Feasible: {requested_kw} kW fits within {headroom:.1f} kW headroom. {basis}"
    elif headroom >= 1.0:
        rec, rec_kw = "partial", math.floor(headroom * 2) / 2
        reason = (f"Partially feasible: only {rec_kw} kW can be cleared without breaching limits "
                  f"(or sanction {requested_kw} kW with export limiting). {basis}")
    else:
        rec, rec_kw = "reject", 0.0
        reason = f"Not feasible: DTR is saturated (headroom {headroom:.1f} kW). Needs DTR augmentation. {basis}"

    return {
        "dtr_id": dtr_id, "dtr_code": hc["dtr_code"], "scheme": scheme,
        "requested_kw": requested_kw, "recommendation": rec, "recommended_kw": rec_kw,
        "headroom_kw": round(headroom, 1), "queued_ahead_kw": round(queued, 1),
        "binding_constraint": constraint, "reason": reason,
        "evaluated_at": datetime.now().isoformat(timespec="seconds"),
    }
