"""Network master data: substations, feeders, DTRs, consumers (CRUD; writes are admin-only)."""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.database import fetch_all, fetch_one, get_db
from app.schemas import DtrIn, DtrUpdate, FeederIn
from app.security import current_user, require_admin

router = APIRouter(prefix="/api", tags=["assets"], dependencies=[Depends(current_user)])


def _unique_violation(exc: sqlite3.IntegrityError) -> HTTPException:
    if "UNIQUE" in str(exc):
        return HTTPException(status.HTTP_409_CONFLICT, "Code already exists")
    return HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid reference (check parent id)")


@router.get("/substations")
def list_substations(conn: sqlite3.Connection = Depends(get_db)):
    return fetch_all(conn, "SELECT * FROM substations ORDER BY code")


# ----------------------------------------------------------------- feeders
@router.get("/feeders")
def list_feeders(conn: sqlite3.Connection = Depends(get_db)):
    return fetch_all(conn, """
        SELECT f.*, s.code AS substation_code, COUNT(d.id) AS dtr_count
        FROM feeders f JOIN substations s ON s.id = f.substation_id
        LEFT JOIN dtrs d ON d.feeder_id = f.id
        GROUP BY f.id ORDER BY f.code""")


@router.post("/feeders", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def create_feeder(body: FeederIn, conn: sqlite3.Connection = Depends(get_db)):
    try:
        new_id = conn.execute(
            "INSERT INTO feeders (substation_id, code, name, voltage_kv, rating_kva) VALUES (?, ?, ?, ?, ?)",
            (body.substation_id, body.code, body.name, body.voltage_kv, body.rating_kva),
        ).lastrowid
    except sqlite3.IntegrityError as exc:
        raise _unique_violation(exc)
    return fetch_one(conn, "SELECT * FROM feeders WHERE id = ?", (new_id,))


@router.put("/feeders/{feeder_id}", dependencies=[Depends(require_admin)])
def update_feeder(feeder_id: int, body: FeederIn, conn: sqlite3.Connection = Depends(get_db)):
    try:
        cur = conn.execute(
            "UPDATE feeders SET substation_id = ?, code = ?, name = ?, voltage_kv = ?, rating_kva = ? WHERE id = ?",
            (body.substation_id, body.code, body.name, body.voltage_kv, body.rating_kva, feeder_id),
        )
    except sqlite3.IntegrityError as exc:
        raise _unique_violation(exc)
    if cur.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Feeder not found")
    return fetch_one(conn, "SELECT * FROM feeders WHERE id = ?", (feeder_id,))


@router.delete("/feeders/{feeder_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_feeder(feeder_id: int, conn: sqlite3.Connection = Depends(get_db)):
    if conn.execute("DELETE FROM feeders WHERE id = ?", (feeder_id,)).rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Feeder not found")
    return Response(status_code=204)


# ----------------------------------------------------------------- DTRs
@router.get("/dtrs")
def list_dtrs(feeder_id: int | None = None, conn: sqlite3.Connection = Depends(get_db)):
    sql = """
        SELECT d.*, f.code AS feeder_code,
               COALESCE(SUM(c.pv_kw), 0) AS pv_kw, COUNT(c.id) AS consumer_count
        FROM dtrs d JOIN feeders f ON f.id = d.feeder_id
        LEFT JOIN consumers c ON c.dtr_id = d.id
        {where} GROUP BY d.id ORDER BY d.code"""
    if feeder_id:
        return fetch_all(conn, sql.format(where="WHERE d.feeder_id = ?"), (feeder_id,))
    return fetch_all(conn, sql.format(where=""))


@router.get("/dtrs/{dtr_id}")
def get_dtr(dtr_id: int, conn: sqlite3.Connection = Depends(get_db)):
    dtr = fetch_one(conn, "SELECT d.*, f.code AS feeder_code FROM dtrs d JOIN feeders f ON f.id = d.feeder_id "
                          "WHERE d.id = ?", (dtr_id,))
    if not dtr:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "DTR not found")
    dtr["consumers"] = fetch_all(conn, "SELECT * FROM consumers WHERE dtr_id = ? ORDER BY pv_kw DESC, account_no",
                                 (dtr_id,))
    dtr["recent_readings"] = fetch_all(conn, "SELECT ts, load_kw, solar_kw, net_kw, voltage_pu FROM readings "
                                             "WHERE dtr_id = ? ORDER BY ts DESC LIMIT 48", (dtr_id,))[::-1]
    return dtr


@router.post("/dtrs", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def create_dtr(body: DtrIn, conn: sqlite3.Connection = Depends(get_db)):
    try:
        new_id = conn.execute(
            "INSERT INTO dtrs (feeder_id, code, name, rating_kva, area_type) VALUES (?, ?, ?, ?, ?)",
            (body.feeder_id, body.code, body.name, body.rating_kva, body.area_type),
        ).lastrowid
    except sqlite3.IntegrityError as exc:
        raise _unique_violation(exc)
    return fetch_one(conn, "SELECT * FROM dtrs WHERE id = ?", (new_id,))


@router.put("/dtrs/{dtr_id}", dependencies=[Depends(require_admin)])
def update_dtr(dtr_id: int, body: DtrUpdate, conn: sqlite3.Connection = Depends(get_db)):
    changes = body.model_dump(exclude_none=True)
    if not fetch_one(conn, "SELECT id FROM dtrs WHERE id = ?", (dtr_id,)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "DTR not found")
    if changes:
        assignments = ", ".join(f"{k} = ?" for k in changes)  # keys come from the validated schema only
        conn.execute(f"UPDATE dtrs SET {assignments} WHERE id = ?", (*changes.values(), dtr_id))
    return fetch_one(conn, "SELECT * FROM dtrs WHERE id = ?", (dtr_id,))


@router.delete("/dtrs/{dtr_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_dtr(dtr_id: int, conn: sqlite3.Connection = Depends(get_db)):
    if conn.execute("DELETE FROM dtrs WHERE id = ?", (dtr_id,)).rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "DTR not found")
    return Response(status_code=204)
