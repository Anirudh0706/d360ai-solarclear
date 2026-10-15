"""D360 AI Copilot: a tool-calling planning agent.

Loop: model picks tools -> we run the deterministic analytics -> model writes the answer.
Token budget: short system prompt, last 6 chat turns only (each clipped), compact JSON
tool results, at most MAX_ROUNDS tool rounds. Without LLM credentials a rule-based
router answers the same questions with the same tools (mode = "offline").
Languages: English and Telugu (lang = "en" | "te").
"""
import json
import re
import sqlite3

from app.agent.llm import complete, get_client, usage_of
from app.agent.tools import TOOL_SPECS, run_tool, tool_result_text
from app.analytics.grid import place
from app.i18n import normalise, tr, word

MAX_ROUNDS = 4
HISTORY_TURNS = 6
HISTORY_CHARS = 600

SYSTEM_PROMPT = (
    "You are D360 AI SolarClear, a planning assistant for an Indian power distribution utility. You answer questions on "
    "rooftop / PM-KUSUM solar hosting capacity, solar and net-export forecasts, voltage and reverse-flow risk, "
    "saturated DTRs and net-meter feasibility. Take every number from tools; never estimate. Reply in at most "
    "150 words, using short bullets, DTR/feeder codes with their Telangana locality (e.g. DTR-S1-02 (Farooqnagar)) "
    "and units (kW, kVA, pu). You recommend; engineers approve. "
    "If asked what you are, you are the D360 AI engine; do not name any underlying model or vendor."
)
TELUGU_INSTRUCTION = (
    " Reply in clear, simple Telugu (తెలుగు script) suitable for field engineers. Keep DTR/feeder codes, numbers "
    "and units (kW, kVA, pu) unchanged. Only DTR, feeder and voltage may stay in English; otherwise use Telugu: "
    "hosting capacity = హోస్టింగ్ సామర్థ్యం, headroom = అదనపు సామర్థ్యం, queue = క్యూలో ఉన్న దరఖాస్తులు, "
    "recommendation = సిఫారసు, approve = ఆమోదం, reject = తిరస్కరణ, augmentation = సామర్థ్యం పెంపు, "
    "saturated = సంతృప్తం, reverse flow = రివర్స్ ఫ్లో, export = ఎగుమతి."
)


def _record(conn: sqlite3.Connection, user_id: int, question: str, result: dict) -> None:
    conn.execute(
        "INSERT INTO agent_runs (user_id, kind, question, answer, tools_used, mode, prompt_tokens, completion_tokens) "
        "VALUES (?, 'chat', ?, ?, ?, ?, ?, ?)",
        (user_id, question, result["answer"], ",".join(result["tools_used"]), result["mode"],
         result["usage"]["prompt_tokens"], result["usage"]["completion_tokens"]),
    )


def chat(conn: sqlite3.Connection, user_id: int, message: str, history: list[dict] | None = None,
         lang: str = "en") -> dict:
    lang = normalise(lang)
    client = get_client()
    if client is None:
        result = offline_answer(conn, message, lang)
    else:
        try:
            result = _llm_chat(conn, client, message, history or [], lang)
        except Exception as exc:  # network / quota / auth problem: degrade gracefully
            result = offline_answer(conn, message, lang)
            result["answer"] = tr("bot.engine_down", lang, err=type(exc).__name__) + result["answer"]
    _record(conn, user_id, message, result)
    return result


def _llm_chat(conn: sqlite3.Connection, client, message: str, history: list[dict], lang: str) -> dict:
    system = SYSTEM_PROMPT + (TELUGU_INSTRUCTION if lang == "te" else "")
    messages = [{"role": "system", "content": system}]
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
        "answer": answer or tr("bot.no_answer", lang),
        "tools_used": tools_used,
        "mode": "d360",
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }


# ---------------------------------------------------------------- offline router
DTR_RE = re.compile(r"dtr[-\s]?([a-z]\d)[-\s]?(\d{1,2})", re.I)
FEEDER_RE = re.compile(r"(?:fdr|feeder|ఫీడర్)[-\s]?([a-z]\d)\b", re.I)
KW_RE = re.compile(r"(\d+(?:\.\d+)?)\s*kw", re.I)

# Intent keywords in English and Telugu.
KEYWORDS = {
    "forecast": ("forecast", "tomorrow", "generation", "export", "next", "అంచనా", "రేపు", "ఉత్పత్తి", "ఎగుమతి"),
    "risk": ("risk", "voltage", "reverse", "overvoltage", "ప్రమాద", "వోల్టేజ్", "రివర్స్"),
    "saturated": ("saturat", "full", "no capacity", "watch", "సంతృప్త", "నిండి", "పర్యవేక్షణ"),
    "watch": ("watch", "పర్యవేక్షణ"),
    "applications": ("application", "pending", "దరఖాస్తు", "పెండింగ్"),
    "kusum": ("kusum", "కుసుమ్"),
}


def _has(text: str, intent: str) -> bool:
    return any(w in text for w in KEYWORDS[intent])


def _dtr_by_place(conn: sqlite3.Connection, message: str) -> str | None:
    """Find a DTR by locality name (English or Telugu) mentioned in the question, longest name first."""
    text = message.lower()
    for row in conn.execute("SELECT code, name, name_te FROM dtrs ORDER BY LENGTH(name) DESC"):
        if row["name"].lower() in text or (row["name_te"] and row["name_te"] in message):
            return row["code"]
    return None


def offline_answer(conn: sqlite3.Connection, message: str, lang: str = "en") -> dict:
    """Keyword intent router over the same tools. Zero tokens, always available."""
    text = message.lower()
    dtr_m, feeder_m, kw_m = DTR_RE.search(message), FEEDER_RE.search(message), KW_RE.search(message)
    dtr_code = f"DTR-{dtr_m.group(1).upper()}-{int(dtr_m.group(2)):02d}" if dtr_m else _dtr_by_place(conn, message)
    feeder_code = f"FDR-{feeder_m.group(1).upper()}" if feeder_m else None
    scheme = "kusum" if _has(text, "kusum") else "rooftop"

    if dtr_code and kw_m:
        tool, args = "netmeter_feasibility", {"dtr_code": dtr_code, "kw": float(kw_m.group(1)), "scheme": scheme}
    elif dtr_code and _has(text, "forecast"):
        tool, args = "solar_forecast", {"dtr_code": dtr_code, "hours": 48}
    elif dtr_code:
        tool, args = "dtr_hosting_capacity", {"dtr_code": dtr_code}
    elif _has(text, "risk"):
        tool, args = "forecast_risks", {"feeder_code": feeder_code}
    elif _has(text, "saturated"):
        tool, args = "list_dtrs", {"status": "watch" if _has(text, "watch") else "saturated", "feeder_code": feeder_code}
    elif _has(text, "applications"):
        tool, args = "list_applications", {"status": "all"}
    elif feeder_code:
        tool, args = "list_dtrs", {"status": "all", "feeder_code": feeder_code}
    else:
        tool, args = "network_overview", {}

    result = run_tool(conn, tool, args)
    if "error" in result and dtr_code and "Unknown DTR" in result["error"]:
        result = {"error": tr("bot.unknown_dtr", lang, code=args.get("dtr_code"))}
    return {"answer": _format(tool, result, lang), "tools_used": [tool], "mode": "offline",
            "usage": {"prompt_tokens": 0, "completion_tokens": 0}}


def _format(tool: str, r: dict, lang: str) -> str:
    te = lang == "te"
    if "error" in r:
        return r["error"]
    if tool == "netmeter_feasibility":
        return tr("bot.feasibility", lang, rec=word(f"rec.{r['recommendation']}"), rec_kw=r["recommended_kw"],
                  kw=r["requested_kw"], reason=r["reason_te"] if te else r["reason"])
    if tool == "dtr_hosting_capacity":
        lim = r["limits_kw"]
        months = (tr("bot.months", lang, n=r["months_to_saturation"]) if r["months_to_saturation"] is not None
                  else tr("bot.na", lang))
        return tr("bot.hosting", lang, dtr=place(r), kva=f"{r['rating_kva']:.0f}", feeder=r["feeder_code"],
                  status=word(f"status.{r['status']}"), pv=r["existing_pv_kw"], util=r["utilisation_pct"],
                  hc=r["hosting_kw"], label=word(f"limit.{r['binding_constraint']}"), rf=lim["reverse_flow"],
                  v=lim["voltage"], pc=lim["policy_cap"], pending=r["pending_kw"], months=months)
    if tool == "solar_forecast":
        s = r["summary"]
        line = tr("bot.forecast", lang, dtr=r["dtr_code"], src=r["weather_source"], s=s["solar_energy_kwh"],
                  e=s["export_energy_kwh"], pe=s["peak_export_kw"], mv=s["max_voltage_pu"], rh=s["risk_hours"])
        return line + "".join(
            f"\n- {p['ts']}: {', '.join(tr(f'riskname.{x}', lang) for x in p['risks'])} "
            f"({p['voltage_pu']} pu, {p['net_export_kw']} kW)" for p in r["risk_hours"])
    if tool == "forecast_risks":
        if not r["events"]:
            return tr("bot.no_risks", lang)
        return tr("bot.risks", lang, n=r["count"]) + "".join(
            tr("bot.risk_line", lang, sev=word(f"status.{e['severity']}"), dtr=place(e),
               risk=word(f"riskname.{e['risk']}"), detail=e["detail_te"] if te else e["detail"],
               hours=e["hours"], first=e["first_at"]) for e in r["events"])
    if tool == "list_dtrs":
        if not r["dtrs"]:
            return tr("bot.no_dtrs", lang)
        return tr("bot.dtrs", lang, n=r["count"]) + "".join(
            tr("bot.dtr_line", lang, dtr=place(d), util=d["utilisation_pct"], hc=d["hosting_kw"],
               status=word(f"status.{d['status']}")) for d in r["dtrs"])
    if tool == "list_applications":
        return tr("bot.apps", lang) + "".join(
            tr("bot.app_line", lang, id=a["id"], name=a["applicant_name"], kw=a["requested_kw"], dtr=a["dtr_code"],
               status=word(f"status.{a['status']}"))
            + (f" -> {tr('rec.' + a['recommendation'], lang)} {a['recommended_kw']} kW" if a["recommendation"] else "")
            for a in r["applications"])
    return tr("bot.overview", lang) + "".join(
        tr("bot.feeder_line", lang, f=f"{f['feeder_code']} ({f['feeder_name_te'] if te else f['feeder_name']})", pv=f["existing_pv_kw"], hc=f["hosting_kw"],
           sat=f["saturated_dtrs"], watch=f["watch_dtrs"]) for f in r["feeders"])
