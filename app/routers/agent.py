"""Agent endpoints (copilot chat, Grid-Watch scan, run history) and alerts."""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status

from app.agent.copilot import chat
from app.agent.gridwatch import run_scan
from app.config import settings
from app.database import fetch_all, get_db
from app.i18n import get_lang
from app.schemas import ChatIn, ScanIn
from app.security import current_user

router = APIRouter(prefix="/api", tags=["agent"])


@router.get("/agent/status")
def agent_status(_: dict = Depends(current_user)):
    # Branded name only: the underlying provider and deployment are not exposed to clients.
    return {"llm_enabled": settings.llm_enabled, "engine": "D360 AI" if settings.llm_enabled else "offline"}


@router.post("/agent/chat")
def agent_chat(body: ChatIn, conn: sqlite3.Connection = Depends(get_db), user: dict = Depends(current_user),
               lang: str = Depends(get_lang)):
    return chat(conn, user["id"], body.message.strip(), [t.model_dump() for t in body.history], lang)


@router.post("/agent/scan")
def agent_scan(body: ScanIn, conn: sqlite3.Connection = Depends(get_db), user: dict = Depends(current_user),
               lang: str = Depends(get_lang)):
    return run_scan(conn, user["id"], body.with_brief, lang)


@router.get("/agent/runs")
def agent_runs(conn: sqlite3.Connection = Depends(get_db), _: dict = Depends(current_user)):
    runs = fetch_all(conn, "SELECT r.*, u.name AS user_name FROM agent_runs r LEFT JOIN users u ON u.id = r.user_id "
                           "ORDER BY r.id DESC LIMIT 50")
    totals = fetch_all(conn, "SELECT COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens, "
                             "COALESCE(SUM(completion_tokens), 0) AS completion_tokens FROM agent_runs")[0]
    return {"runs": runs, "totals": totals}


@router.get("/alerts")
def list_alerts(include_acknowledged: bool = False, conn: sqlite3.Connection = Depends(get_db),
                _: dict = Depends(current_user)):
    where = "" if include_acknowledged else "WHERE a.acknowledged = 0"
    return fetch_all(conn, f"""
        SELECT a.*, d.code AS dtr_code, d.name AS dtr_name, d.name_te AS dtr_name_te FROM alerts a JOIN dtrs d ON d.id = a.dtr_id {where}
        ORDER BY a.acknowledged, CASE a.severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, a.id""")


@router.post("/alerts/{alert_id}/ack")
def acknowledge(alert_id: int, conn: sqlite3.Connection = Depends(get_db), _: dict = Depends(current_user)):
    if conn.execute("UPDATE alerts SET acknowledged = 1 WHERE id = ?", (alert_id,)).rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")
    return {"id": alert_id, "acknowledged": True}
