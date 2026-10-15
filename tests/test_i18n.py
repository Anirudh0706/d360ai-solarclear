"""English / Telugu support: locale completeness, Telugu server text, Telugu copilot."""
import json
import re
from pathlib import Path

from app.i18n import MESSAGES, tr
from tests.conftest import dtr_id

STATIC = Path(__file__).resolve().parent.parent / "static"
TELUGU = re.compile(r"[ఀ-౿]")  # Telugu Unicode block
TE = {"X-Lang": "te"}


def _locale(lang):
    return json.loads((STATIC / "locales" / f"{lang}.json").read_text(encoding="utf-8"))


def test_locales_have_same_keys():
    en, te = _locale("en"), _locale("te")
    missing = set(en) - set(te)
    assert not missing, f"Telugu locale is missing: {sorted(missing)}"


def test_every_ui_key_is_defined():
    """Every literal t("key") in app.js and data-i18n in index.html must exist in both locales."""
    source = (STATIC / "app.js").read_text(encoding="utf-8") + (STATIC / "index.html").read_text(encoding="utf-8")
    used = set(re.findall(r"""\bt\(\s*["']([a-zA-Z]+\.[\w.-]+)["']""", source))
    used |= set(re.findall(r'data-i18n(?:-placeholder)?="([\w.-]+)"', source))
    used |= set(re.findall(r'["\'](copilot\.s\d|btn\.\w+|status\.\w+)["\']', source))
    for lang in ("en", "te"):
        missing = used - set(_locale(lang))
        assert not missing, f"{lang} locale is missing keys used by the UI: {sorted(missing)}"


def test_telugu_ui_strings_are_telugu():
    te = _locale("te")
    for key in ("nav.dashboard", "nav.applications", "dash.title", "status.saturated", "feas.title"):
        assert TELUGU.search(te[key]), key


def test_server_messages_have_both_languages():
    for key, entry in MESSAGES.items():
        assert entry.get("en") and entry.get("te"), key


def test_feasibility_reason_in_telugu(client, engineer):
    res = client.post("/api/analytics/feasibility", headers=engineer,
                      json={"dtr_id": dtr_id(client, engineer, "DTR-S1-02"), "kw": 5}).json()
    assert res["recommendation"] == "reject"
    assert "Not feasible" in res["reason"]
    assert TELUGU.search(res["reason_te"]) and "DTR-S1-02" in res["reason_te"]


def test_application_reason_stored_in_both_languages(client, engineer):
    app = client.post("/api/applications", headers=engineer,
                      json={"dtr_id": dtr_id(client, engineer, "DTR-N2-03"), "applicant_name": "రమేష్", "requested_kw": 3}).json()
    ev = client.post(f"/api/applications/{app['id']}/evaluate", headers=engineer).json()["application"]
    assert ev["applicant_name"] == "రమేష్"  # Telugu names round-trip through SQLite
    assert ev["decision_reason"].startswith("Feasible")
    assert TELUGU.search(ev["decision_reason_te"])


def test_scan_alerts_and_summary_in_telugu(client, engineer):
    res = client.post("/api/agent/scan", headers={**engineer, **TE}, json={}).json()
    assert TELUGU.search(res["summary"])
    alerts = client.get("/api/alerts", headers=engineer).json()
    assert alerts and all(a["message"] and TELUGU.search(a["message_te"]) for a in alerts)


def test_offline_copilot_answers_in_telugu(client, engineer):
    r = client.post("/api/agent/chat", headers={**engineer, **TE},
                    json={"message": "DTR-N2-03 కి 5 kW రూఫ్‌టాప్ కలపవచ్చా?"}).json()
    assert r["tools_used"] == ["netmeter_feasibility"]
    assert TELUGU.search(r["answer"]) and "అనుమతించవచ్చు" in r["answer"]


def test_offline_router_understands_telugu_keywords(client, engineer):
    sat = client.post("/api/agent/chat", headers={**engineer, **TE}, json={"message": "సంతృప్త డీటీఆర్‌లు ఏవి?"}).json()
    assert sat["tools_used"] == ["list_dtrs"] and TELUGU.search(sat["answer"])
    risk = client.post("/api/agent/chat", headers={**engineer, **TE}, json={"message": "వోల్టేజ్ ప్రమాదం ఉందా?"}).json()
    assert risk["tools_used"] == ["forecast_risks"]


def test_default_language_is_english(client, engineer):
    r = client.post("/api/agent/chat", headers=engineer, json={"message": "Which DTRs are saturated?"}).json()
    assert not TELUGU.search(r["answer"])


def test_dtrs_have_telangana_locality_names(client, engineer):
    hc = client.get(f"/api/analytics/hosting/dtr/{dtr_id(client, engineer, 'DTR-S1-02')}", headers=engineer).json()
    assert hc["dtr_name"] == "Farooqnagar" and hc["dtr_name_te"] == "ఫరూఖ్‌నగర్"
    assert "Shadnagar" in hc["feeder_name"] and TELUGU.search(hc["feeder_name_te"])


def test_dtr_found_by_locality_name(client, engineer):
    en = client.post("/api/agent/chat", headers=engineer, json={"message": "Hosting capacity at Pet Basheerabad?"}).json()
    assert en["tools_used"] == ["dtr_hosting_capacity"] and "DTR-N1-03 (Pet Basheerabad)" in en["answer"]
    te = client.post("/api/agent/chat", headers={**engineer, **TE}, json={"message": "ఫరూఖ్‌నగర్ లో 3 kW కలపవచ్చా?"}).json()
    assert te["tools_used"] == ["netmeter_feasibility"] and "ఫరూఖ్‌నగర్" in te["answer"]


def test_alerts_name_the_locality(client, engineer):
    client.post("/api/agent/scan", headers=engineer, json={})
    alert = next(a for a in client.get("/api/alerts", headers=engineer).json() if a["dtr_code"] == "DTR-S1-02")
    assert "DTR-S1-02 (Farooqnagar)" in alert["message"] and "ఫరూఖ్‌నగర్" in alert["message_te"]


def test_tr_resolves_translatable_values():
    assert tr("alert.watch", "te", dtr="DTR-X", util=75, hc=10).startswith("DTR-X హోస్టింగ్")
    assert tr("limit.voltage", "xx") == "voltage rise"  # unknown language falls back to English
