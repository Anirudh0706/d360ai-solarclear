"""Forecasting, hosting capacity, risk detection, saturation and feasibility endpoints."""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.analytics.grid import detect_risks, evaluate_request, forecast_dtr, hosting_capacity, network_hosting
from app.config import settings
from app.database import fetch_one, get_db
from app.schemas import FeasibilityIn
from app.security import current_user

router = APIRouter(prefix="/api/analytics", tags=["analytics"], dependencies=[Depends(current_user)])


def _require_dtr(conn: sqlite3.Connection, dtr_id: int) -> None:
    if not fetch_one(conn, "SELECT id FROM dtrs WHERE id = ?", (dtr_id,)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "DTR not found")


@router.get("/overview")
def overview(conn: sqlite3.Connection = Depends(get_db)):
    net = network_hosting(conn)
    dtrs = net["dtrs"]
    open_alerts = fetch_one(conn, "SELECT COUNT(*) AS n, COALESCE(SUM(severity = 'critical'), 0) AS critical "
                                  "FROM alerts WHERE acknowledged = 0")
    pending = fetch_one(conn, "SELECT COUNT(*) AS n, COALESCE(SUM(requested_kw), 0) AS kw FROM applications "
                              "WHERE status IN ('pending', 'evaluated')")
    return {
        "kpis": {
            "dtrs": len(dtrs),
            "installed_pv_kw": round(sum(d["existing_pv_kw"] for d in dtrs), 1),
            "hosting_headroom_kw": round(sum(f["hosting_kw"] for f in net["feeders"]), 1),
            "saturated_dtrs": sum(d["status"] == "saturated" for d in dtrs),
            "watch_dtrs": sum(d["status"] == "watch" for d in dtrs),
            "open_alerts": open_alerts["n"], "critical_alerts": open_alerts["critical"],
            "open_applications": pending["n"], "queued_kw": round(pending["kw"], 1),
        },
        "limits": {"voltage_upper_pu": settings.voltage_upper_pu,
                   "reverse_flow_limit_pct": settings.reverse_flow_limit_pct,
                   "policy_cap_pct": settings.policy_cap_pct},
        **net,
    }


@router.get("/hosting/dtr/{dtr_id}")
def dtr_hosting(dtr_id: int, conn: sqlite3.Connection = Depends(get_db)):
    _require_dtr(conn, dtr_id)
    return hosting_capacity(conn, dtr_id)


@router.get("/hosting/feeder/{feeder_id}")
def feeder_hosting(feeder_id: int, conn: sqlite3.Connection = Depends(get_db)):
    result = network_hosting(conn, feeder_id)
    if not result["feeders"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Feeder not found")
    return result


@router.get("/forecast/dtr/{dtr_id}")
def dtr_forecast(dtr_id: int, hours: int = Query(48, ge=1, le=72), conn: sqlite3.Connection = Depends(get_db)):
    _require_dtr(conn, dtr_id)
    return forecast_dtr(conn, dtr_id, hours)


@router.get("/risks")
def risks(feeder_id: int | None = None, conn: sqlite3.Connection = Depends(get_db)):
    return detect_risks(conn, feeder_id)


@router.get("/saturated")
def saturated(conn: sqlite3.Connection = Depends(get_db)):
    dtrs = [d for d in network_hosting(conn)["dtrs"] if d["status"] in ("saturated", "watch")]
    return sorted(dtrs, key=lambda d: -d["utilisation_pct"])


@router.post("/feasibility")
def feasibility(body: FeasibilityIn, conn: sqlite3.Connection = Depends(get_db)):
    _require_dtr(conn, body.dtr_id)
    return evaluate_request(conn, body.dtr_id, body.kw, body.scheme)
