"""Grid-Watch: the autonomous agent run.

Perceive  -> forecast every DTR, compute hosting capacity
Decide    -> raise overvoltage / reverse-flow / saturation / pipeline alerts,
             evaluate every pending application in queue order
Act       -> store alerts, push critical ones to the webhook, log the run
Explain   -> optional single LLM call turns the compact findings into an ops brief

All decisions are deterministic, so a scan costs zero tokens unless a brief is requested.
"""
import json
import sqlite3

from app.agent.llm import complete, get_client, usage_of
from app.analytics.grid import detect_risks, network_hosting
from app.database import fetch_all
from app.services.clearance import evaluate_application
from app.services.notify import send_webhook

BRIEF_PROMPT = (
    "You write a shift brief for a distribution utility's planning control room. From the JSON findings, write "
    "at most 5 bullets (max 90 words): most urgent risks first, name DTR codes, and give one concrete action each."
)


def run_scan(conn: sqlite3.Connection, user_id: int | None, with_brief: bool = False) -> dict:
    network = network_hosting(conn)
    risks = detect_risks(conn)

    # Re-scan replaces previous unacknowledged alerts so the list never duplicates.
    conn.execute("DELETE FROM alerts WHERE acknowledged = 0")
    alerts = []
    for e in risks:
        alerts.append((e["dtr_id"], e["risk"], e["severity"],
                       f"{e['dtr_code']}: forecast {e['detail']} for {e['hours']} h starting {e['first_at']}",
                       e["first_at"]))
    for d in network["dtrs"]:
        if d["status"] == "saturated":
            alerts.append((d["dtr_id"], "saturation", "critical",
                           f"{d['dtr_code']} saturated: {d['utilisation_pct']}% of hosting capacity used, "
                           f"{d['hosting_kw']} kW left ({d['binding_constraint']}). Hold new net-meter clearances "
                           f"or plan DTR augmentation.", None))
        elif d["status"] == "watch":
            if d["pending_kw"] >= d["hosting_kw"]:
                msg = f"{d['dtr_code']}: pending applications {d['pending_kw']} kW exceed headroom {d['hosting_kw']} kW."
                kind = "pipeline"
            elif d["months_to_saturation"] is not None and d["months_to_saturation"] <= 12:
                msg = (f"{d['dtr_code']} will saturate in ~{d['months_to_saturation']} months at "
                       f"{d['growth_kw_per_month']} kW/month adoption ({d['hosting_kw']} kW left).")
                kind = "saturation"
            else:
                msg = f"{d['dtr_code']} at {d['utilisation_pct']}% of hosting capacity ({d['hosting_kw']} kW left)."
                kind = "saturation"
            alerts.append((d["dtr_id"], kind, "warning", msg, None))
    conn.executemany(
        "INSERT INTO alerts (dtr_id, alert_type, severity, message, forecast_for) VALUES (?, ?, ?, ?, ?)", alerts
    )

    evaluated = []
    for app in fetch_all(conn, "SELECT id FROM applications WHERE status = 'pending' ORDER BY id"):
        result = evaluate_application(conn, app["id"])
        evaluated.append({"id": app["id"], "dtr": result["dtr_code"], "kw": result["requested_kw"],
                          "rec": result["recommendation"], "rec_kw": result["recommended_kw"]})

    critical = [a[3] for a in alerts if a[2] == "critical"]
    statuses = [d["status"] for d in network["dtrs"]]
    summary = (f"Scanned {len(statuses)} DTRs: {statuses.count('saturated')} saturated, {statuses.count('watch')} on watch. "
               f"{len(risks)} forecast risk event(s), {len(alerts)} alert(s) raised ({len(critical)} critical), "
               f"{len(evaluated)} application(s) evaluated.")
    notified = send_webhook("SolarClear Grid-Watch: critical alerts", critical)

    brief, mode, tokens = None, "offline", (0, 0)
    client = get_client() if with_brief else None
    if client:
        findings = {
            "summary": summary,
            "alerts": [{"sev": a[2], "msg": a[3]} for a in alerts if a[2] == "critical"][:8],
            "warnings": len(alerts) - len(critical),
            "applications": evaluated[:10],
        }
        try:
            response = complete(client, [{"role": "system", "content": BRIEF_PROMPT},
                                         {"role": "user", "content": json.dumps(findings, separators=(",", ":"))}],
                                max_tokens=1500)
            brief, mode, tokens = (response.choices[0].message.content or "").strip() or None, "azure", usage_of(response)
        except Exception as exc:  # brief is optional; the scan itself already succeeded
            brief = f"(Brief unavailable: {type(exc).__name__})"

    conn.execute(
        "INSERT INTO agent_runs (user_id, kind, question, answer, tools_used, mode, prompt_tokens, completion_tokens) "
        "VALUES (?, 'scan', 'grid-watch scan', ?, 'network_hosting,detect_risks,evaluate_application', ?, ?, ?)",
        (user_id, brief or summary, mode, tokens[0], tokens[1]),
    )
    return {
        "summary": summary, "brief": brief, "mode": mode,
        "alerts_created": len(alerts), "critical_alerts": len(critical),
        "risk_events": len(risks), "applications_evaluated": evaluated,
        "webhook_notified": notified,
        "usage": {"prompt_tokens": tokens[0], "completion_tokens": tokens[1]},
    }
