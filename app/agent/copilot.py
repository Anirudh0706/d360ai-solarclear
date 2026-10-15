"""Planning Copilot: a tool-calling agent on Azure OpenAI.

Loop: model picks tools -> we run the deterministic analytics -> model writes the answer.
Token budget: short system prompt, last 6 chat turns only (each clipped), compact JSON
tool results, at most MAX_ROUNDS tool rounds. Without Azure credentials a rule-based
router answers the same questions with the same tools (mode = "offline").
"""
import json
import re
import sqlite3

from app.agent.llm import complete, get_client, usage_of
from app.agent.tools import TOOL_SPECS, run_tool, tool_result_text

MAX_ROUNDS = 4
HISTORY_TURNS = 6
HISTORY_CHARS = 600

SYSTEM_PROMPT = (
    "You are D360 AI SolarClear, a planning assistant for an Indian power distribution utility. You answer questions on "
    "rooftop / PM-KUSUM solar hosting capacity, solar and net-export forecasts, voltage and reverse-flow risk, "
    "saturated DTRs and net-meter feasibility. Take every number from tools; never estimate. Reply in at most "
    "150 words, using short bullets, DTR/feeder codes and units (kW, kVA, pu). You recommend; engineers approve. "
    "If asked what you are, you are the D360 AI engine; do not name any underlying model or vendor."
)


def _record(conn: sqlite3.Connection, user_id: int, question: str, result: dict) -> None:
    conn.execute(
        "INSERT INTO agent_runs (user_id, kind, question, answer, tools_used, mode, prompt_tokens, completion_tokens) "
        "VALUES (?, 'chat', ?, ?, ?, ?, ?, ?)",
        (user_id, question, result["answer"], ",".join(result["tools_used"]), result["mode"],
         result["usage"]["prompt_tokens"], result["usage"]["completion_tokens"]),
    )


def chat(conn: sqlite3.Connection, user_id: int, message: str, history: list[dict] | None = None) -> dict:
    client = get_client()
    if client is None:
        result = offline_answer(conn, message)
    else:
        try:
            result = _azure_chat(conn, client, message, history or [])
        except Exception as exc:  # network / quota / auth problem: degrade gracefully
            result = offline_answer(conn, message)
            result["answer"] = f"(D360 AI engine unavailable: {type(exc).__name__}. Rule-based answer.)\n\n" + result["answer"]
    _record(conn, user_id, message, result)
    return result


def _azure_chat(conn: sqlite3.Connection, client, message: str, history: list[dict]) -> dict:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in history[-HISTORY_TURNS:]:
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            messages.append({"role": turn["role"], "content": str(turn["content"])[:HISTORY_CHARS]})
    messages.append({"role": "user", "content": message})

    tools_used, prompt_tokens, completion_tokens = [], 0, 0
    answer = ""
    for round_no in range(MAX_ROUNDS + 1):
        # Final round withholds tools to force an answer.
        response = complete(client, messages, TOOL_SPECS if round_no < MAX_ROUNDS else None)
        p, c = usage_of(response)
        prompt_tokens, completion_tokens = prompt_tokens + p, completion_tokens + c
        msg = response.choices[0].message
        if not msg.tool_calls:
            answer = (msg.content or "").strip()
            break
        messages.append({
            "role": "assistant", "content": msg.content or "",
            "tool_calls": [{"id": t.id, "type": "function",
                            "function": {"name": t.function.name, "arguments": t.function.arguments}}
                           for t in msg.tool_calls],
        })
        for call in msg.tool_calls:
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            tools_used.append(call.function.name)
            result = run_tool(conn, call.function.name, args)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": tool_result_text(result)})

    return {
        "answer": answer or "I could not produce an answer within the token budget. Please narrow the question.",
        "tools_used": tools_used,
        "mode": "azure",
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }


# ---------------------------------------------------------------- offline router
DTR_RE = re.compile(r"dtr[-\s]?([a-z]\d)[-\s]?(\d{1,2})", re.I)
FEEDER_RE = re.compile(r"(?:fdr|feeder)[-\s]?([a-z]\d)\b", re.I)
KW_RE = re.compile(r"(\d+(?:\.\d+)?)\s*kw", re.I)


def offline_answer(conn: sqlite3.Connection, message: str) -> dict:
    """Keyword intent router over the same tools. Zero tokens, always available."""
    text = message.lower()
    dtr_m, feeder_m, kw_m = DTR_RE.search(message), FEEDER_RE.search(message), KW_RE.search(message)
    dtr_code = f"DTR-{dtr_m.group(1).upper()}-{int(dtr_m.group(2)):02d}" if dtr_m else None
    feeder_code = f"FDR-{feeder_m.group(1).upper()}" if feeder_m else None
    scheme = "kusum" if "kusum" in text else "rooftop"

    if dtr_code and kw_m:
        tool, args = "netmeter_feasibility", {"dtr_code": dtr_code, "kw": float(kw_m.group(1)), "scheme": scheme}
    elif dtr_code and any(w in text for w in ("forecast", "tomorrow", "generation", "export", "next")):
        tool, args = "solar_forecast", {"dtr_code": dtr_code, "hours": 48}
    elif dtr_code:
        tool, args = "dtr_hosting_capacity", {"dtr_code": dtr_code}
    elif any(w in text for w in ("risk", "voltage", "reverse", "overvoltage")):
        tool, args = "forecast_risks", {"feeder_code": feeder_code}
    elif any(w in text for w in ("saturat", "full", "no capacity", "watch")):
        tool, args = "list_dtrs", {"status": "watch" if "watch" in text else "saturated", "feeder_code": feeder_code}
    elif "application" in text or "pending" in text:
        tool, args = "list_applications", {"status": "all"}
    elif feeder_code:
        tool, args = "list_dtrs", {"status": "all", "feeder_code": feeder_code}
    else:
        tool, args = "network_overview", {}

    result = run_tool(conn, tool, args)
    return {"answer": _format(tool, result), "tools_used": [tool], "mode": "offline",
            "usage": {"prompt_tokens": 0, "completion_tokens": 0}}


def _format(tool: str, r: dict) -> str:
    if "error" in r:
        return r["error"]
    if tool == "netmeter_feasibility":
        return f"**{r['recommendation'].upper()}** - recommended {r['recommended_kw']} kW of {r['requested_kw']} kW.\n{r['reason']}"
    if tool == "dtr_hosting_capacity":
        lim = r["limits_kw"]
        months = f"{r['months_to_saturation']} months" if r["months_to_saturation"] is not None else "n/a"
        return (f"**{r['dtr_code']}** ({r['rating_kva']:.0f} kVA, {r['feeder_code']}) - status **{r['status']}**\n"
                f"- Installed PV {r['existing_pv_kw']} kW, utilisation {r['utilisation_pct']}%\n"
                f"- Hosting capacity **{r['hosting_kw']} kW** (binding: {r['binding_constraint']})\n"
                f"- Limits: reverse flow {lim['reverse_flow']} kW, voltage {lim['voltage']} kW, policy {lim['policy_cap']} kW\n"
                f"- Queue {r['pending_kw']} kW pending; saturation in {months} at current adoption")
    if tool == "solar_forecast":
        s = r["summary"]
        line = (f"**{r['dtr_code']} forecast** ({r['weather_source']}): solar {s['solar_energy_kwh']} kWh, "
                f"export {s['export_energy_kwh']} kWh, peak export {s['peak_export_kw']} kW, "
                f"max voltage {s['max_voltage_pu']} pu, {s['risk_hours']} risk hour(s).")
        return line + "".join(f"\n- {p['ts']}: {', '.join(p['risks'])} ({p['voltage_pu']} pu, {p['net_export_kw']} kW)"
                              for p in r["risk_hours"])
    if tool == "forecast_risks":
        if not r["events"]:
            return "No overvoltage or reverse-flow events forecast in the next 48 hours."
        return f"**{r['count']} forecast risk event(s):**" + "".join(
            f"\n- [{e['severity']}] {e['dtr_code']} {e['risk']}: {e['detail']}, {e['hours']} h from {e['first_at']}"
            for e in r["events"])
    if tool == "list_dtrs":
        if not r["dtrs"]:
            return "No DTRs match."
        return f"**{r['count']} DTR(s):**" + "".join(
            f"\n- {d['dtr_code']}: {d['utilisation_pct']}% used, {d['hosting_kw']} kW headroom ({d['status']})"
            for d in r["dtrs"])
    if tool == "list_applications":
        return "**Applications:**" + "".join(
            f"\n- #{a['id']} {a['applicant_name']} {a['requested_kw']} kW on {a['dtr_code']}: {a['status']}"
            + (f" -> {a['recommendation']} {a['recommended_kw']} kW" if a["recommendation"] else "")
            for a in r["applications"])
    return "**Network overview:**" + "".join(
        f"\n- {f['feeder_code']}: {f['existing_pv_kw']} kW PV, {f['hosting_kw']} kW headroom, "
        f"{f['saturated_dtrs']} saturated / {f['watch_dtrs']} watch DTRs" for f in r["feeders"])
