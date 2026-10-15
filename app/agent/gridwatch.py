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
from app.analytics.grid import detect_risks, network_hosting, place
from app.database import fetch_all
from app.i18n import both, tr, word
from app.services.clearance import evaluate_application
from app.services.notify import send_webhook

BRIEF_PROMPT = (
    "You write a shift brief for a distribution utility's planning control room. From the JSON findings, write "
    "at most 5 bullets (max 90 words): most urgent risks first, name DTR codes, and give one concrete action each."
)
BRIEF_TELUGU = (
    " Write the bullets in Telugu script; keep DTR codes, numbers and units (kW, kVA, pu) as they are. Use Telugu "
    "terms: hosting capacity = హోస్టింగ్ సామర్థ్యం, headroom = అదనపు సామర్థ్యం, net-meter clearances = నెట్-మీటర్ "
    "అనుమతులు, augmentation = సామర్థ్యం పెంపు, h = గంటలు."
)


def run_scan(conn: sqlite3.Connection, user_id: int | None, with_brief: bool = False, lang: str = "en") -> dict:
    network = network_hosting(conn)
    risks = detect_risks(conn)

    # Re-scan replaces previous unacknowledged alerts so the list never duplicates.
    conn.execute("DELETE FROM alerts WHERE acknowledged = 0")
    # Each alert: (dtr_id, type, severity, message_en, message_te, forecast_for)
    alerts = []
    for e in risks:
        msg = {lg: tr("alert.risk", lg, dtr=place(e), detail=e["detail" if lg == "en" else "detail_te"],
                        hours=e["hours"], first=e["first_at"]) for lg in ("en", "te")}
        alerts.append((e["dtr_id"], e["risk"], e["severity"], msg["en"], msg["te"], e["first_at"]))
    for d in network["dtrs"]:
        common = {"dtr": place(d), "util": d["utilisation_pct"], "hc": d["hosting_kw"]}
        if d["status"] == "saturated":
            en, te = both("alert.saturated", label=word(f"limit.{d['binding_constraint']}"), **common)
            alerts.append((d["dtr_id"], "saturation", "critical", en, te, None))
        elif d["status"] == "watch":
            if d["pending_kw"] >= d["hosting_kw"]:
                en, te = both("alert.pipeline", pending=d["pending_kw"], **common)
                kind = "pipeline"
            elif d["months_to_saturation"] is not None and d["months_to_saturation"] <= 12:
                en, te = both("alert.will_saturate", months=d["months_to_saturation"],
                              rate=d["growth_kw_per_month"], **common)
                kind = "saturation"
            else:
                en, te = both("alert.watch", **common)
                kind = "saturation"
            alerts.append((d["dtr_id"], kind, "warning", en, te, None))
    conn.executemany(
        "INSERT INTO alerts (dtr_id, alert_type, severity, message, message_te, forecast_for) VALUES (?, ?, ?, ?, ?, ?)",
        alerts,
    )

    evaluated = []
    for app in fetch_all(conn, "SELECT id FROM applications WHERE status = 'pending' ORDER BY id"):
        result = evaluate_application(conn, app["id"])
        evaluated.append({"id": app["id"], "dtr": result["dtr_code"], "kw": result["requested_kw"],
                          "rec": result["recommendation"], "rec_kw": result["recommended_kw"]})

    critical = [a[3] for a in alerts if a[2] == "critical"]  # English text, for the webhook
    statuses = [d["status"] for d in network["dtrs"]]
    counts = {"n": len(statuses), "sat": statuses.count("saturated"), "watch": statuses.count("watch"),
              "risks": len(risks), "alerts": len(alerts), "crit": len(critical), "apps": len(evaluated)}
    summary_en = tr("scan.summary", "en", **counts)
    summary = tr("scan.summary", lang, **counts)
    notified = send_webhook("SolarClear Grid-Watch: critical alerts", critical)

    brief, mode, tokens = None, "offline", (0, 0)
    client = get_client() if with_brief else None
    if client:
        # Findings go to the model in English (fewer tokens); only the output language changes.
        findings = {
            "summary": summary_en,
            "alerts": [{"sev": a[2], "msg": a[3]} for a in alerts if a[2] == "critical"][:8],
            "warnings": len(alerts) - len(critical),
            "applications": evaluated[:10],
        }
        prompt = BRIEF_PROMPT + (BRIEF_TELUGU if lang == "te" else "")
        try:
            response = complete(client, [{"role": "system", "content": prompt},
                                         {"role": "user", "content": json.dumps(findings, separators=(",", ":"))}],
                                max_tokens=1500)
            brief, mode, tokens = (response.choices[0].message.content or "").strip() or None, "azure", usage_of(response)
        except Exception as exc:  # brief is optional; the scan itself already succeeded
            brief = f"(Brief unavailable: {type(exc).__name__})"

    conn.execute(
        "INSERT INTO agent_runs (user_id, kind, question, answer, tools_used, mode, prompt_tokens, completion_tokens) "
        "VALUES (?, 'scan', 'grid-watch scan', ?, 'network_hosting,detect_risks,evaluate_application', ?, ?, ?)",
        (user_id, brief or summary_en, mode, tokens[0], tokens[1]),
    )
    return {
        "summary": summary, "brief": brief, "mode": mode,
        "alerts_created": len(alerts), "critical_alerts": len(critical),
        "risk_events": len(risks), "applications_evaluated": evaluated,
        "webhook_notified": notified,
        "usage": {"prompt_tokens": tokens[0], "completion_tokens": tokens[1]},
    }
