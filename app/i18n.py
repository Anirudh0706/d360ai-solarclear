"""English / Telugu text for messages the server generates (clearance reasons, alerts, scan
summary, offline copilot answers). The UI's own labels live in static/locales/*.json.

The client picks a language with the `X-Lang: te|en` header. Generated text that is stored
(alerts, application reasons) is saved in both languages so switching is instant."""
from fastapi import Header

LANGS = ("en", "te")

MESSAGES: dict[str, dict[str, str]] = {
    # ---- binding constraints
    "limit.reverse_flow": {"en": "reverse power flow", "te": "రివర్స్ పవర్ ఫ్లో"},
    "limit.voltage": {"en": "voltage rise", "te": "వోల్టేజ్ పెరుగుదల"},
    "limit.policy_cap": {"en": "regulatory DTR cap", "te": "నియంత్రణ డీటీఆర్ పరిమితి"},
    "limit.feeder_reverse_flow": {"en": "11 kV feeder reverse flow", "te": "11 kV ఫీడర్ రివర్స్ ఫ్లో"},
    "limit.sum_of_dtrs": {"en": "DTR limits on the feeder", "te": "ఫీడర్‌లోని డీటీఆర్ పరిమితులు"},
    # ---- clearance reasons
    "clear.basis": {
        "en": "{dtr} ({kva} kVA) has {pv} kW PV installed, hosting capacity {hc} kW limited by {label}, "
              "{queued} kW already queued ahead.",
        "te": "{dtr} ({kva} kVA) పై ఇప్పటికే {pv} kW సౌర విద్యుత్ ఏర్పాటైంది; హోస్టింగ్ సామర్థ్యం {hc} kW, "
              "దీనిని {label} పరిమితం చేస్తోంది; ముందు వరుసలో {queued} kW దరఖాస్తులు ఉన్నాయి.",
    },
    "clear.clear": {
        "en": "Feasible: {kw} kW fits within {headroom} kW headroom. {basis}",
        "te": "సాధ్యమే: {kw} kW, అందుబాటులో ఉన్న {headroom} kW అదనపు సామర్థ్యంలో సరిపోతుంది. {basis}",
    },
    "clear.partial": {
        "en": "Partially feasible: only {rec} kW can be cleared without breaching limits "
              "(or sanction {kw} kW with export limiting). {basis}",
        "te": "పాక్షికంగా సాధ్యం: పరిమితులు దాటకుండా {rec} kW మాత్రమే అనుమతించవచ్చు "
              "(లేదా ఎగుమతి పరిమితితో {kw} kW మంజూరు చేయవచ్చు). {basis}",
    },
    "clear.reject": {
        "en": "Not feasible: DTR is saturated (headroom {headroom} kW). Needs DTR augmentation. {basis}",
        "te": "సాధ్యం కాదు: డీటీఆర్ సంతృప్త స్థితిలో ఉంది (అదనపు సామర్థ్యం {headroom} kW). "
              "డీటీఆర్ సామర్థ్యం పెంపు అవసరం. {basis}",
    },
    "clear.note": {"en": " Engineer note: {note}", "te": " ఇంజనీర్ వ్యాఖ్య: {note}"},
    # ---- risk details and alerts
    "risk.overvoltage": {
        "en": "voltage up to {peak:.3f} pu (limit {limit})",
        "te": "వోల్టేజ్ {peak:.3f} pu వరకు (పరిమితి {limit})",
    },
    "risk.reverse_flow": {
        "en": "reverse flow up to {peak:.0f} kW ({pct:.0f}% of {kva:.0f} kVA)",
        "te": "రివర్స్ ఫ్లో {peak:.0f} kW వరకు ({kva:.0f} kVA లో {pct:.0f}%)",
    },
    "alert.risk": {
        "en": "{dtr}: forecast {detail} for {hours} h starting {first}",
        "te": "{dtr}: {first} నుండి {hours} గంటల పాటు {detail} అంచనా",
    },
    "alert.saturated": {
        "en": "{dtr} saturated: {util}% of hosting capacity used, {hc} kW left ({label}). "
              "Hold new net-meter clearances or plan DTR augmentation.",
        "te": "{dtr} సంతృప్తమైంది: హోస్టింగ్ సామర్థ్యంలో {util}% వినియోగమైంది, {hc} kW మాత్రమే మిగిలింది ({label}). "
              "కొత్త నెట్-మీటర్ అనుమతులు నిలిపివేయండి లేదా డీటీఆర్ సామర్థ్యం పెంపును ప్లాన్ చేయండి.",
    },
    "alert.pipeline": {
        "en": "{dtr}: pending applications {pending} kW exceed headroom {hc} kW.",
        "te": "{dtr}: పెండింగ్ దరఖాస్తులు {pending} kW, అదనపు సామర్థ్యం {hc} kW ను మించాయి.",
    },
    "alert.will_saturate": {
        "en": "{dtr} will saturate in ~{months} months at {rate} kW/month adoption ({hc} kW left).",
        "te": "{dtr} నెలకు {rate} kW వృద్ధి రేటుతో సుమారు {months} నెలల్లో సంతృప్తమవుతుంది ({hc} kW మిగిలింది).",
    },
    "alert.watch": {
        "en": "{dtr} at {util}% of hosting capacity ({hc} kW left).",
        "te": "{dtr} హోస్టింగ్ సామర్థ్యంలో {util}% వద్ద ఉంది ({hc} kW మిగిలింది).",
    },
    "scan.summary": {
        "en": "Scanned {n} DTRs: {sat} saturated, {watch} on watch. {risks} forecast risk event(s), "
              "{alerts} alert(s) raised ({crit} critical), {apps} application(s) evaluated.",
        "te": "{n} డీటీఆర్‌లను స్కాన్ చేసింది: {sat} సంతృప్తం, {watch} పర్యవేక్షణలో. {risks} అంచనా ప్రమాద సంఘటనలు, "
              "{alerts} హెచ్చరికలు ({crit} తీవ్రమైనవి), {apps} దరఖాస్తుల మూల్యాంకనం పూర్తయింది.",
    },
    # ---- offline copilot answers
    "bot.feasibility": {
        "en": "**{rec}** - recommended {rec_kw} kW of {kw} kW.\n{reason}",
        "te": "**{rec}** - {kw} kW లో {rec_kw} kW సిఫారసు చేయబడింది.\n{reason}",
    },
    "bot.hosting": {
        "en": "**{dtr}** ({kva} kVA, {feeder}) - status **{status}**\n"
              "- Installed PV {pv} kW, utilisation {util}%\n"
              "- Hosting capacity **{hc} kW** (binding: {label})\n"
              "- Limits: reverse flow {rf} kW, voltage {v} kW, policy {pc} kW\n"
              "- Queue {pending} kW pending; saturation in {months} at current adoption",
        "te": "**{dtr}** ({kva} kVA, {feeder}) - స్థితి **{status}**\n"
              "- ఏర్పాటైన సౌర విద్యుత్ {pv} kW, వినియోగం {util}%\n"
              "- హోస్టింగ్ సామర్థ్యం **{hc} kW** (నిర్ణాయక పరిమితి: {label})\n"
              "- పరిమితులు: రివర్స్ ఫ్లో {rf} kW, వోల్టేజ్ {v} kW, విధాన పరిమితి {pc} kW\n"
              "- క్యూలో {pending} kW పెండింగ్; ప్రస్తుత వృద్ధి రేటుతో సంతృప్తతకు {months}",
    },
    "bot.months": {"en": "{n} months", "te": "{n} నెలలు"},
    "bot.na": {"en": "n/a", "te": "వర్తించదు"},
    "bot.forecast": {
        "en": "**{dtr} forecast** ({src}): solar {s} kWh, export {e} kWh, peak export {pe} kW, "
              "max voltage {mv} pu, {rh} risk hour(s).",
        "te": "**{dtr} అంచనా** ({src}): సౌర ఉత్పత్తి {s} kWh, ఎగుమతి {e} kWh, గరిష్ఠ ఎగుమతి {pe} kW, "
              "గరిష్ఠ వోల్టేజ్ {mv} pu, {rh} ప్రమాద గంటలు.",
    },
    "bot.no_risks": {
        "en": "No overvoltage or reverse-flow events forecast in the next 48 hours.",
        "te": "రాబోయే 48 గంటల్లో అధిక వోల్టేజ్ లేదా రివర్స్-ఫ్లో సంఘటనలు అంచనా వేయబడలేదు.",
    },
    "bot.risks": {"en": "**{n} forecast risk event(s):**", "te": "**{n} అంచనా ప్రమాద సంఘటనలు:**"},
    "bot.risk_line": {
        "en": "\n- [{sev}] {dtr} {risk}: {detail}, {hours} h from {first}",
        "te": "\n- [{sev}] {dtr} {risk}: {detail}, {first} నుండి {hours} గంటలు",
    },
    "bot.no_dtrs": {"en": "No DTRs match.", "te": "సరిపోయే డీటీఆర్‌లు లేవు."},
    "bot.dtrs": {"en": "**{n} DTR(s):**", "te": "**{n} డీటీఆర్‌లు:**"},
    "bot.dtr_line": {
        "en": "\n- {dtr}: {util}% used, {hc} kW headroom ({status})",
        "te": "\n- {dtr}: {util}% వినియోగం, {hc} kW అదనపు సామర్థ్యం ({status})",
    },
    "bot.apps": {"en": "**Applications:**", "te": "**దరఖాస్తులు:**"},
    "bot.app_line": {
        "en": "\n- #{id} {name} {kw} kW on {dtr}: {status}",
        "te": "\n- #{id} {name} {kw} kW, {dtr} పై: {status}",
    },
    "bot.overview": {"en": "**Network overview:**", "te": "**నెట్‌వర్క్ సారాంశం:**"},
    "bot.feeder_line": {
        "en": "\n- {f}: {pv} kW PV, {hc} kW headroom, {sat} saturated / {watch} watch DTRs",
        "te": "\n- {f}: {pv} kW సౌర, {hc} kW అదనపు సామర్థ్యం, {sat} సంతృప్త / {watch} పర్యవేక్షణ డీటీఆర్‌లు",
    },
    "bot.unknown_dtr": {
        "en": "Unknown DTR {code}. Use list_dtrs to see valid codes.",
        "te": "{code} అనే డీటీఆర్ లేదు. సరైన కోడ్‌ల కోసం డీటీఆర్ జాబితా చూడండి.",
    },
    "bot.engine_down": {
        "en": "(D360 AI engine unavailable: {err}. Rule-based answer.)\n\n",
        "te": "(D360 AI ఇంజిన్ అందుబాటులో లేదు: {err}. నియమ ఆధారిత సమాధానం.)\n\n",
    },
    "bot.no_answer": {
        "en": "I could not produce an answer within the token budget. Please narrow the question.",
        "te": "టోకెన్ పరిమితిలో సమాధానం ఇవ్వలేకపోయాను. దయచేసి ప్రశ్నను మరింత స్పష్టంగా అడగండి.",
    },
    # ---- status words used inside generated text
    "status.saturated": {"en": "saturated", "te": "సంతృప్తం"},
    "status.watch": {"en": "watch", "te": "పర్యవేక్షణ"},
    "status.available": {"en": "available", "te": "అందుబాటులో ఉంది"},
    "status.pending": {"en": "pending", "te": "పెండింగ్"},
    "status.evaluated": {"en": "evaluated", "te": "మూల్యాంకనం పూర్తి"},
    "status.approved": {"en": "approved", "te": "ఆమోదించబడింది"},
    "status.rejected": {"en": "rejected", "te": "తిరస్కరించబడింది"},
    "status.critical": {"en": "critical", "te": "తీవ్రమైనది"},
    "status.warning": {"en": "warning", "te": "హెచ్చరిక"},
    "rec.clear": {"en": "CLEAR", "te": "అనుమతించవచ్చు"},
    "rec.partial": {"en": "PARTIAL", "te": "పాక్షికం"},
    "rec.reject": {"en": "REJECT", "te": "తిరస్కరణ"},
    "riskname.overvoltage": {"en": "overvoltage", "te": "అధిక వోల్టేజ్"},
    "riskname.reverse_flow": {"en": "reverse flow", "te": "రివర్స్ ఫ్లో"},
}


def normalise(lang: str | None) -> str:
    return "te" if (lang or "").lower().startswith("te") else "en"


def get_lang(x_lang: str | None = Header(default=None)) -> str:
    """FastAPI dependency: language requested by the client (X-Lang header), default English."""
    return normalise(x_lang)


def tr(key: str, lang: str = "en", **values) -> str:
    """Format a message. A value may itself be {'en': ..., 'te': ...}; it resolves to `lang`."""
    lang = normalise(lang)
    entry = MESSAGES.get(key)
    if not entry:
        return key
    resolved = {k: (v.get(lang, v["en"]) if isinstance(v, dict) else v) for k, v in values.items()}
    return entry.get(lang, entry["en"]).format(**resolved)


def word(key: str) -> dict[str, str]:
    """A translatable word to pass as a value into tr()/both()."""
    return MESSAGES.get(key, {"en": key, "te": key})


def both(key: str, **values) -> tuple[str, str]:
    """English and Telugu versions of the same message (for text we store)."""
    return tr(key, "en", **values), tr(key, "te", **values)
