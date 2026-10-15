"""Agent behaviour: offline router, Grid-Watch scan, alerts, and the Azure tool-calling loop (mocked)."""
import json
from types import SimpleNamespace

from app.agent import copilot, gridwatch
from app.agent.tools import run_tool


def ask(client, headers, message):
    res = client.post("/api/agent/chat", headers=headers, json={"message": message})
    assert res.status_code == 200, res.text
    return res.json()


# ---------- offline router (no Azure keys)
def test_offline_feasibility_intent(client, engineer):
    r = ask(client, engineer, "Can DTR-N2-03 take a 5 kW rooftop?")
    assert r["mode"] == "offline" and r["tools_used"] == ["netmeter_feasibility"]
    assert "CLEAR" in r["answer"]


def test_offline_forecast_intent(client, engineer):
    r = ask(client, engineer, "forecast export for dtr s1 02 tomorrow")
    assert r["tools_used"] == ["solar_forecast"] and "DTR-S1-02 forecast" in r["answer"]


def test_offline_saturation_and_overview(client, engineer):
    assert ask(client, engineer, "Which DTRs are saturated?")["tools_used"] == ["list_dtrs"]
    assert ask(client, engineer, "hello")["tools_used"] == ["network_overview"]


def test_unknown_dtr_handled(client, engineer):
    r = ask(client, engineer, "hosting capacity of DTR-X9-99")
    assert "Unknown DTR" in r["answer"]


def test_chat_validation(client, engineer):
    assert client.post("/api/agent/chat", headers=engineer, json={"message": ""}).status_code == 422


# ---------- autonomous Grid-Watch scan
def test_scan_raises_alerts_and_evaluates_applications(client, engineer):
    res = client.post("/api/agent/scan", headers=engineer, json={"with_brief": False}).json()
    assert res["alerts_created"] > 0 and res["critical_alerts"] > 0
    assert res["usage"] == {"prompt_tokens": 0, "completion_tokens": 0}  # deterministic scan costs no tokens
    alerts = client.get("/api/alerts", headers=engineer).json()
    assert any(a["alert_type"] == "saturation" and a["dtr_code"] == "DTR-S1-02" for a in alerts)
    pending = client.get("/api/applications?status=pending", headers=engineer).json()
    assert pending == []  # every pending application was evaluated


def test_rescan_does_not_duplicate_alerts(client, engineer):
    client.post("/api/agent/scan", headers=engineer, json={})
    first = len(client.get("/api/alerts", headers=engineer).json())
    client.post("/api/agent/scan", headers=engineer, json={})
    assert len(client.get("/api/alerts", headers=engineer).json()) == first


def test_acknowledge_alert(client, engineer):
    alert = client.get("/api/alerts", headers=engineer).json()[0]
    assert client.post(f"/api/alerts/{alert['id']}/ack", headers=engineer).status_code == 200
    open_ids = [a["id"] for a in client.get("/api/alerts", headers=engineer).json()]
    assert alert["id"] not in open_ids
    assert client.post("/api/alerts/999999/ack", headers=engineer).status_code == 404


def test_agent_runs_logged(client, engineer):
    data = client.get("/api/agent/runs", headers=engineer).json()
    kinds = {r["kind"] for r in data["runs"]}
    assert {"chat", "scan"} <= kinds


# ---------- Azure tool-calling loop with a fake client
class FakeAzure:
    """Round 1: model asks for a tool. Round 2: model answers from the tool result."""

    def __init__(self):
        self.calls = []

    def respond(self, messages):
        self.calls.append(messages)
        usage = SimpleNamespace(prompt_tokens=100, completion_tokens=20)
        if len(self.calls) == 1:
            call = SimpleNamespace(id="call_1", function=SimpleNamespace(
                name="dtr_hosting_capacity", arguments=json.dumps({"dtr_code": "DTR-N1-03"})))
            msg = SimpleNamespace(content=None, tool_calls=[call])
        else:
            tool_msg = next(m for m in messages if m["role"] == "tool")
            hosting = json.loads(tool_msg["content"])["hosting_kw"]
            msg = SimpleNamespace(content=f"DTR-N1-03 can host {hosting} kW more.", tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=usage)


def test_azure_agent_loop_uses_tools(client, engineer, monkeypatch):
    fake = FakeAzure()
    monkeypatch.setattr(copilot, "get_client", lambda: fake)
    monkeypatch.setattr(copilot, "complete", lambda client, messages, tools=None, max_tokens=None: fake.respond(messages))
    r = ask(client, engineer, "How much more solar can DTR-N1-03 take?")
    assert r["mode"] == "azure"
    assert r["tools_used"] == ["dtr_hosting_capacity"]
    assert r["usage"] == {"prompt_tokens": 200, "completion_tokens": 40}
    assert "DTR-N1-03 can host" in r["answer"]
    # The tool result is compact JSON (token economy): no learned-model internals.
    tool_msg = next(m for m in fake.calls[1] if m["role"] == "tool")
    assert "model" not in json.loads(tool_msg["content"])


def test_azure_failure_falls_back_to_offline(client, engineer, monkeypatch):
    def boom(*_, **__):
        raise ConnectionError("network down")

    monkeypatch.setattr(copilot, "get_client", lambda: object())
    monkeypatch.setattr(copilot, "complete", boom)
    r = ask(client, engineer, "Which DTRs are saturated?")
    assert r["mode"] == "offline" and "D360 AI engine unavailable" in r["answer"]


def test_scan_brief_uses_single_llm_call(client, engineer, monkeypatch):
    calls = []

    def fake_complete(client, messages, tools=None, max_tokens=None):
        calls.append(messages)
        msg = SimpleNamespace(content="- DTR-S1-02: hold clearances", tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)],
                               usage=SimpleNamespace(prompt_tokens=300, completion_tokens=50))

    monkeypatch.setattr(gridwatch, "get_client", lambda: object())
    monkeypatch.setattr(gridwatch, "complete", fake_complete)
    res = client.post("/api/agent/scan", headers=engineer, json={"with_brief": True}).json()
    assert len(calls) == 1 and res["mode"] == "azure" and res["brief"].startswith("- DTR-S1-02")


def test_tool_input_validation(db):
    assert "error" in run_tool(db, "netmeter_feasibility", {"dtr_code": "DTR-N1-01", "kw": "abc"})
    assert "error" in run_tool(db, "netmeter_feasibility", {"dtr_code": "DTR-N1-01", "kw": -2})
    assert "error" in run_tool(db, "list_dtrs", {"feeder_code": "FDR-ZZ"})
    assert "error" in run_tool(db, "nonexistent_tool", {"dtr_code": "DTR-N1-01"})
