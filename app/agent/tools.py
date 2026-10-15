"""Tools the agent can call. Each returns a compact dict so tool results stay cheap in tokens.
All tools are read-only: the agent recommends, engineers approve."""
import json
import sqlite3

from app.analytics.grid import detect_risks, evaluate_request, forecast_dtr, hosting_capacity, network_hosting
from app.database import fetch_all, fetch_one

MAX_TOOL_RESULT_CHARS = 2500


def _fn(name: str, description: str, properties: dict | None = None, required: list[str] | None = None) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties or {}, "required": required or []},
    }}


DTR = {"type": "string", "description": "DTR code (e.g. DTR-N1-03) or its locality name (e.g. Pet Basheerabad)"}
FEEDER = {"type": "string", "description": "Feeder code, e.g. FDR-S1"}

TOOL_SPECS = [
    _fn("network_overview", "Per-feeder totals: installed PV, hosting headroom, saturated/watch DTR counts."),
    _fn("dtr_hosting_capacity", "Hosting capacity of one DTR: limits (reverse flow, voltage, policy), "
        "utilisation, status, pending queue, months to saturation.", {"dtr_code": DTR}, ["dtr_code"]),
    _fn("list_dtrs", "List DTRs filtered by status, sorted by utilisation.",
        {"status": {"type": "string", "enum": ["saturated", "watch", "available", "all"]}, "feeder_code": FEEDER}),
    _fn("solar_forecast", "Solar generation, net export and voltage forecast for a DTR (summary + peak hours).",
        {"dtr_code": DTR, "hours": {"type": "integer", "minimum": 1, "maximum": 48}}, ["dtr_code"]),
    _fn("forecast_risks", "Forecast overvoltage / reverse-flow events in the next 48 h.", {"feeder_code": FEEDER}),
    _fn("netmeter_feasibility", "Technical clearance check for adding solar on a DTR (queue-aware).",
        {"dtr_code": DTR, "kw": {"type": "number"}, "scheme": {"type": "string", "enum": ["rooftop", "kusum"]}},
        ["dtr_code", "kw"]),
    _fn("list_applications", "Net-meter / KUSUM applications with recommendation and status.",
        {"status": {"type": "string", "enum": ["pending", "evaluated", "approved", "rejected", "all"]}}),
]


def _dtr_id(conn: sqlite3.Connection, code: str) -> int | None:
    """Accept a DTR code or a locality name in English or Telugu."""
    key = (code or "").strip()
    row = fetch_one(conn, "SELECT id FROM dtrs WHERE UPPER(code) = UPPER(?) OR LOWER(name) = LOWER(?) OR name_te = ? "
                          "ORDER BY UPPER(code) = UPPER(?) DESC LIMIT 1", (key, key, key, key))
    return row["id"] if row else None


def _feeder_id(conn: sqlite3.Connection, code: str | None) -> int | None:
    if not code:
        return None
    row = fetch_one(conn, "SELECT id FROM feeders WHERE UPPER(code) = UPPER(?)", (code.strip(),))
    return row["id"] if row else -1


def _compact_dtr(d: dict) -> dict:
    keys = ("dtr_code", "dtr_name", "dtr_name_te", "feeder_code", "rating_kva", "existing_pv_kw", "hosting_kw", "utilisation_pct",
            "binding_constraint", "status", "pending_kw", "months_to_saturation")
    return {k: d[k] for k in keys}


def run_tool(conn: sqlite3.Connection, name: str, args: dict) -> dict:
    """Execute one tool call. Errors come back as data so the agent can recover."""
    if name == "network_overview":
        return {"feeders": network_hosting(conn)["feeders"]}

    if name == "list_dtrs":
        feeder_id = _feeder_id(conn, args.get("feeder_code"))
        if feeder_id == -1:
            return {"error": f"Unknown feeder {args.get('feeder_code')}"}
        status = args.get("status", "all")
        rows = [d for d in network_hosting(conn, feeder_id)["dtrs"] if status in ("all", None) or d["status"] == status]
        rows.sort(key=lambda d: -d["utilisation_pct"])
        return {"count": len(rows), "dtrs": [_compact_dtr(d) for d in rows[:12]]}

    if name == "forecast_risks":
        feeder_id = _feeder_id(conn, args.get("feeder_code"))
        if feeder_id == -1:
            return {"error": f"Unknown feeder {args.get('feeder_code')}"}
        events = detect_risks(conn, feeder_id)
        return {"count": len(events), "events": events[:10]}

    if name == "list_applications":
        status = args.get("status") or "all"
        sql = ("SELECT a.id, d.code AS dtr_code, a.applicant_name, a.scheme, a.requested_kw, a.status, "
               "a.recommendation, a.recommended_kw FROM applications a JOIN dtrs d ON d.id = a.dtr_id")
        rows = fetch_all(conn, sql + ("" if status == "all" else " WHERE a.status = ?") + " ORDER BY a.id DESC LIMIT 15",
                         () if status == "all" else (status,))
        return {"applications": rows}

    dtr_id = _dtr_id(conn, args.get("dtr_code", ""))
    if dtr_id is None:
        return {"error": f"Unknown DTR {args.get('dtr_code')}. Use list_dtrs to see valid codes."}

    if name == "dtr_hosting_capacity":
        hc = hosting_capacity(conn, dtr_id)
        hc.pop("model", None)
        return hc

    if name == "solar_forecast":
        fc = forecast_dtr(conn, dtr_id, int(args.get("hours") or 24))
        peaks = sorted(fc["points"], key=lambda p: -p["net_export_kw"])[:3]
        risky = [p for p in fc["points"] if p["risks"]][:6]
        return {"dtr_code": fc["dtr_code"], "weather_source": fc["weather_source"], "limits": fc["limits"],
                "summary": fc["summary"], "peak_export_hours": peaks, "risk_hours": risky}

    if name == "netmeter_feasibility":
        try:
            kw = float(args.get("kw"))
        except (TypeError, ValueError):
            return {"error": "kw must be a number"}
        if kw <= 0:
            return {"error": "kw must be positive"}
        return evaluate_request(conn, dtr_id, kw, args.get("scheme") or "rooftop")

    return {"error": f"Unknown tool {name}"}


def _drop_translations(value):
    """Telugu copies (*_te) are for the UI; the model translates itself, so don't spend tokens on them."""
    if isinstance(value, dict):
        return {k: _drop_translations(v) for k, v in value.items() if not k.endswith("_te")}
    if isinstance(value, list):
        return [_drop_translations(v) for v in value]
    return value


def tool_result_text(result: dict) -> str:
    text = json.dumps(_drop_translations(result), separators=(",", ":"), default=str)
    return text if len(text) <= MAX_TOOL_RESULT_CHARS else text[:MAX_TOOL_RESULT_CHARS] + "...(truncated)"
