"""Net-meter / KUSUM application clearance: runs the feasibility engine and stores the result."""
import sqlite3

from app.analytics.grid import evaluate_request
from app.database import fetch_one


def evaluate_application(conn: sqlite3.Connection, app_id: int) -> dict | None:
    """Evaluate one open application against DTR headroom (queue-aware) and save the recommendation."""
    app = fetch_one(conn, "SELECT * FROM applications WHERE id = ?", (app_id,))
    if not app:
        return None
    result = evaluate_request(conn, app["dtr_id"], app["requested_kw"], app["scheme"], app_id=app["id"])
    conn.execute(
        """
        UPDATE applications
        SET status = 'evaluated', recommendation = ?, recommended_kw = ?, binding_constraint = ?,
            decision_reason = ?, decision_reason_te = ?, evaluated_at = datetime('now')
        WHERE id = ?
        """,
        (result["recommendation"], result["recommended_kw"], result["binding_constraint"], result["reason"],
         result["reason_te"], app_id),
    )
    return result


def approve_application(conn: sqlite3.Connection, app: dict, approved_kw: float) -> None:
    """Approval adds the sanctioned PV to the consumer, so hosting capacity updates immediately."""
    if app["consumer_id"]:
        conn.execute(
            "UPDATE consumers SET pv_kw = pv_kw + ?, scheme = ?, pv_commissioned_on = date('now') WHERE id = ?",
            (approved_kw, app["scheme"], app["consumer_id"]),
        )
    else:
        cur = conn.execute(
            "INSERT INTO consumers (dtr_id, account_no, name, category, sanctioned_load_kw, pv_kw, scheme, "
            "pv_commissioned_on) VALUES (?, ?, ?, ?, ?, ?, ?, date('now'))",
            (app["dtr_id"], f"NM{app['id']:06d}", app["applicant_name"],
             "agricultural" if app["scheme"] == "kusum" else "domestic", max(approved_kw, 1), approved_kw, app["scheme"]),
        )
        conn.execute("UPDATE applications SET consumer_id = ? WHERE id = ?", (cur.lastrowid, app["id"]))
