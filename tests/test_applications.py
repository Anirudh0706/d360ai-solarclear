"""Net-meter application workflow: create -> evaluate -> approve/reject, queue awareness, CRUD."""
from tests.conftest import dtr_id


def _create(client, headers, code, kw, name="Test Applicant", scheme="rooftop"):
    res = client.post("/api/applications", headers=headers,
                      json={"dtr_id": dtr_id(client, headers, code), "applicant_name": name, "scheme": scheme, "requested_kw": kw})
    assert res.status_code == 201, res.text
    return res.json()


def test_create_and_evaluate_clear(client, engineer):
    app = _create(client, engineer, "DTR-N2-03", 5)
    assert app["status"] == "pending"
    res = client.post(f"/api/applications/{app['id']}/evaluate", headers=engineer).json()
    assert res["evaluation"]["recommendation"] == "clear"
    assert res["application"]["status"] == "evaluated"


def test_saturated_dtr_rejected(client, engineer):
    app = _create(client, engineer, "DTR-S1-02", 3)
    ev = client.post(f"/api/applications/{app['id']}/evaluate", headers=engineer).json()["evaluation"]
    assert ev["recommendation"] == "reject" and ev["recommended_kw"] == 0


def test_partial_clearance_when_request_exceeds_headroom(client, engineer):
    hc = client.get(f"/api/analytics/hosting/dtr/{dtr_id(client, engineer, 'DTR-S1-04')}", headers=engineer).json()
    app = _create(client, engineer, "DTR-S1-04", hc["hosting_kw"] + 50)
    ev = client.post(f"/api/applications/{app['id']}/evaluate", headers=engineer).json()["evaluation"]
    assert ev["recommendation"] in ("partial", "reject")
    assert ev["recommended_kw"] <= ev["headroom_kw"]


def test_queue_is_first_come_first_served(client, engineer):
    hc = client.get(f"/api/analytics/hosting/dtr/{dtr_id(client, engineer, 'DTR-N1-04')}", headers=engineer).json()
    first = _create(client, engineer, "DTR-N1-04", round(hc["headroom_after_queue_kw"] * 0.8, 1), "First")
    second = _create(client, engineer, "DTR-N1-04", round(hc["headroom_after_queue_kw"] * 0.8, 1), "Second")
    ev1 = client.post(f"/api/applications/{first['id']}/evaluate", headers=engineer).json()["evaluation"]
    ev2 = client.post(f"/api/applications/{second['id']}/evaluate", headers=engineer).json()["evaluation"]
    assert ev1["recommendation"] == "clear"
    assert ev2["recommendation"] in ("partial", "reject")
    assert ev2["queued_ahead_kw"] >= first["requested_kw"]


def test_approval_adds_pv_and_reduces_hosting(client, engineer):
    target = dtr_id(client, engineer, "DTR-N2-03")
    before = client.get(f"/api/analytics/hosting/dtr/{target}", headers=engineer).json()
    app = _create(client, engineer, "DTR-N2-03", 10, "Approve Me")
    client.post(f"/api/applications/{app['id']}/evaluate", headers=engineer)
    decided = client.post(f"/api/applications/{app['id']}/decision", headers=engineer, json={"decision": "approve"}).json()
    assert decided["status"] == "approved" and decided["approved_kw"] == 10 and decided["consumer_id"]
    after = client.get(f"/api/analytics/hosting/dtr/{target}", headers=engineer).json()
    assert after["existing_pv_kw"] == before["existing_pv_kw"] + 10
    assert after["hosting_kw"] < before["hosting_kw"]


def test_decision_requires_evaluation(client, engineer):
    app = _create(client, engineer, "DTR-N1-01", 3)
    res = client.post(f"/api/applications/{app['id']}/decision", headers=engineer, json={"decision": "approve"})
    assert res.status_code == 409


def test_cannot_approve_more_than_requested(client, engineer):
    app = _create(client, engineer, "DTR-N1-01", 3)
    client.post(f"/api/applications/{app['id']}/evaluate", headers=engineer)
    res = client.post(f"/api/applications/{app['id']}/decision", headers=engineer,
                      json={"decision": "approve", "approved_kw": 30})
    assert res.status_code == 400


def test_reject_with_note(client, engineer):
    app = _create(client, engineer, "DTR-N1-01", 2)
    client.post(f"/api/applications/{app['id']}/evaluate", headers=engineer)
    res = client.post(f"/api/applications/{app['id']}/decision", headers=engineer,
                      json={"decision": "reject", "note": "Incomplete documents"}).json()
    assert res["status"] == "rejected" and "Incomplete documents" in res["decision_reason"]


def test_edit_resets_evaluation_and_delete(client, engineer):
    app = _create(client, engineer, "DTR-N1-01", 4)
    client.post(f"/api/applications/{app['id']}/evaluate", headers=engineer)
    edited = client.put(f"/api/applications/{app['id']}", headers=engineer, json={"requested_kw": 6}).json()
    assert edited["requested_kw"] == 6 and edited["status"] == "pending" and edited["recommendation"] is None
    assert client.delete(f"/api/applications/{app['id']}", headers=engineer).status_code == 204
    assert client.get(f"/api/applications/{app['id']}", headers=engineer).status_code == 404


def test_application_validation(client, engineer):
    bad_kw = client.post("/api/applications", headers=engineer,
                         json={"dtr_id": 1, "applicant_name": "X Y", "requested_kw": -1})
    assert bad_kw.status_code == 422
    bad_dtr = client.post("/api/applications", headers=engineer,
                          json={"dtr_id": 999, "applicant_name": "X Y", "requested_kw": 3})
    assert bad_dtr.status_code == 400
    bad_scheme = client.post("/api/applications", headers=engineer,
                             json={"dtr_id": 1, "applicant_name": "X Y", "requested_kw": 3, "scheme": "wind"})
    assert bad_scheme.status_code == 422


def test_list_filter_by_status(client, engineer):
    rows = client.get("/api/applications?status=approved", headers=engineer).json()
    assert rows and all(r["status"] == "approved" for r in rows)
