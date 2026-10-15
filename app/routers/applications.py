"""Net-meter / KUSUM application workflow: create -> evaluate (agent) -> approve/reject (engineer)."""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.database import fetch_all, fetch_one, get_db
from app.i18n import both
from app.schemas import ApplicationIn, ApplicationUpdate, DecisionIn
from app.security import current_user
from app.services.clearance import approve_application, evaluate_application

router = APIRouter(prefix="/api/applications", tags=["applications"])

SELECT_APP = """
    SELECT a.*, d.code AS dtr_code, f.code AS feeder_code, u.name AS decided_by_name
    FROM applications a JOIN dtrs d ON d.id = a.dtr_id JOIN feeders f ON f.id = d.feeder_id
    LEFT JOIN users u ON u.id = a.decided_by"""


def _get(conn: sqlite3.Connection, app_id: int) -> dict:
    app = fetch_one(conn, SELECT_APP + " WHERE a.id = ?", (app_id,))
    if not app:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
    return app


@router.get("")
def list_applications(status_filter: str | None = Query(None, alias="status"), conn: sqlite3.Connection = Depends(get_db),
                      _: dict = Depends(current_user)):
    if status_filter:
        return fetch_all(conn, SELECT_APP + " WHERE a.status = ? ORDER BY a.id DESC", (status_filter,))
    return fetch_all(conn, SELECT_APP + " ORDER BY a.id DESC")


@router.get("/{app_id}")
def get_application(app_id: int, conn: sqlite3.Connection = Depends(get_db), _: dict = Depends(current_user)):
    return _get(conn, app_id)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_application(body: ApplicationIn, conn: sqlite3.Connection = Depends(get_db),
                       user: dict = Depends(current_user)):
    if not fetch_one(conn, "SELECT id FROM dtrs WHERE id = ?", (body.dtr_id,)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "DTR does not exist")
    if body.consumer_id and not fetch_one(conn, "SELECT id FROM consumers WHERE id = ? AND dtr_id = ?",
                                          (body.consumer_id, body.dtr_id)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Consumer is not connected to this DTR")
    new_id = conn.execute(
        "INSERT INTO applications (dtr_id, consumer_id, applicant_name, scheme, requested_kw, created_by) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (body.dtr_id, body.consumer_id, body.applicant_name.strip(), body.scheme, body.requested_kw, user["id"]),
    ).lastrowid
    return _get(conn, new_id)


@router.put("/{app_id}")
def update_application(app_id: int, body: ApplicationUpdate, conn: sqlite3.Connection = Depends(get_db),
                       _: dict = Depends(current_user)):
    app = _get(conn, app_id)
    if app["status"] in ("approved", "rejected"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Decided applications cannot be edited")
    changes = body.model_dump(exclude_none=True)
    if changes:
        # Any edit invalidates the previous evaluation.
        assignments = ", ".join(f"{k} = ?" for k in changes)
        conn.execute(f"UPDATE applications SET {assignments}, status = 'pending', recommendation = NULL, "
                     f"recommended_kw = NULL, decision_reason = NULL, decision_reason_te = NULL WHERE id = ?",
                     (*changes.values(), app_id))
    return _get(conn, app_id)


@router.delete("/{app_id}", status_code=204)
def delete_application(app_id: int, conn: sqlite3.Connection = Depends(get_db), user: dict = Depends(current_user)):
    app = _get(conn, app_id)
    if app["status"] == "approved" and user["role"] != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins can delete approved applications")
    conn.execute("DELETE FROM applications WHERE id = ?", (app_id,))
    return Response(status_code=204)


@router.post("/{app_id}/evaluate")
def evaluate(app_id: int, conn: sqlite3.Connection = Depends(get_db), _: dict = Depends(current_user)):
    app = _get(conn, app_id)
    if app["status"] in ("approved", "rejected"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Application already decided")
    result = evaluate_application(conn, app_id)
    return {"evaluation": result, "application": _get(conn, app_id)}


@router.post("/{app_id}/decision")
def decide(app_id: int, body: DecisionIn, conn: sqlite3.Connection = Depends(get_db),
           user: dict = Depends(current_user)):
    app = _get(conn, app_id)
    if app["status"] != "evaluated":
        raise HTTPException(status.HTTP_409_CONFLICT, "Run the feasibility evaluation before deciding")
    if body.decision == "approve":
        approved_kw = body.approved_kw or app["recommended_kw"]
        if not approved_kw:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing to approve: recommended capacity is 0 kW")
        if approved_kw > app["requested_kw"]:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Approved kW cannot exceed requested kW")
        approve_application(conn, app, approved_kw)
        new_status = "approved"
    else:
        approved_kw, new_status = None, "rejected"
    note, note_te = both("clear.note", note=body.note) if body.note else ("", "")
    conn.execute(
        "UPDATE applications SET status = ?, approved_kw = ?, decided_by = ?, decided_at = datetime('now'), "
        "decision_reason = COALESCE(decision_reason, '') || ?, "
        "decision_reason_te = COALESCE(decision_reason_te, '') || ? WHERE id = ?",
        (new_status, approved_kw, user["id"], note, note_te, app_id),
    )
    return _get(conn, app_id)
