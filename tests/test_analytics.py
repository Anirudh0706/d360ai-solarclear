"""Forecasting, hosting capacity, risk detection and saturation logic."""
from datetime import datetime

import pytest

from app.analytics.grid import build_model, forecast_dtr, hosting_capacity
from app.analytics.solar import clearsky_ghi, linear_fit, pv_output_kw
from tests.conftest import dtr_id


# ---------- physics helpers
def test_clearsky_day_and_night():
    noon = clearsky_ghi(datetime(2026, 10, 15, 12), 17.4, 78.4)
    night = clearsky_ghi(datetime(2026, 10, 15, 23), 17.4, 78.4)
    assert 750 < noon < 1050 and night == 0


def test_pv_output_temperature_derating():
    cool = pv_output_kw(10, 1000, 10, 0.8)
    hot = pv_output_kw(10, 1000, 40, 0.8)
    assert hot < cool <= 10
    assert pv_output_kw(10, 0, 30, 0.8) == 0


def test_linear_fit_recovers_line():
    xs = list(range(20))
    a, b, r2 = linear_fit(xs, [1.02 + 0.001 * x for x in xs])
    assert a == pytest.approx(1.02) and b == pytest.approx(0.001) and r2 == pytest.approx(1.0)


# ---------- learned models
def test_voltage_sensitivity_learned_from_meter_data(client, db, engineer):
    # Seed uses 0.07 pu per (kW/kVA) for urban DTRs -> 0.0007 pu/kW on 100 kVA.
    model = build_model(db, dtr_id(client, engineer, "DTR-N1-01"))
    assert model.v_b == pytest.approx(0.0007, rel=0.2)
    assert model.v_r2 > 0.6
    assert 0.7 <= model.pr <= 0.85  # seeded PR range 0.74-0.82


# ---------- hosting capacity and saturation
def test_saturated_dtr_flagged(client, db, engineer):
    hc = hosting_capacity(db, dtr_id(client, engineer, "DTR-S1-02"))
    assert hc["status"] == "saturated"
    assert hc["hosting_kw"] == 0
    assert hc["binding_constraint"] == "voltage"


def test_lightly_loaded_dtr_available(client, db, engineer):
    hc = hosting_capacity(db, dtr_id(client, engineer, "DTR-N2-03"))
    assert hc["status"] == "available"
    assert hc["hosting_kw"] > 50
    assert hc["hosting_kw"] == min(hc["limits_kw"].values())


def test_overview_endpoint(client, engineer):
    data = client.get("/api/analytics/overview", headers=engineer).json()
    assert data["kpis"]["dtrs"] == 16
    assert data["kpis"]["saturated_dtrs"] >= 2
    assert len(data["feeders"]) == 4
    for f in data["feeders"]:
        members = [d for d in data["dtrs"] if d["feeder_id"] == f["feeder_id"]]
        assert f["hosting_kw"] <= sum(d["hosting_kw"] for d in members) + 0.1


def test_saturated_endpoint_sorted(client, engineer):
    rows = client.get("/api/analytics/saturated", headers=engineer).json()
    assert rows and all(r["status"] in ("saturated", "watch") for r in rows)
    assert [r["utilisation_pct"] for r in rows] == sorted((r["utilisation_pct"] for r in rows), reverse=True)


# ---------- forecasting and risk
def test_forecast_shape_and_physics(client, db, engineer):
    fc = forecast_dtr(db, dtr_id(client, engineer, "DTR-N1-03"), 48)
    assert len(fc["points"]) == 48
    for p in fc["points"]:
        assert p["solar_kw"] >= 0
        assert p["net_export_kw"] == pytest.approx(p["solar_kw"] - p["load_kw"], abs=0.11)
        if p["ghi_wm2"] == 0:
            assert p["solar_kw"] == 0
    assert fc["summary"]["peak_solar_kw"] > 0


def test_forecast_endpoint_validation(client, engineer):
    assert client.get("/api/analytics/forecast/dtr/9999", headers=engineer).status_code == 404
    assert client.get("/api/analytics/forecast/dtr/1?hours=500", headers=engineer).status_code == 422


def test_risk_detection_finds_overloaded_dtr(client, engineer):
    events = client.get("/api/analytics/risks", headers=engineer).json()
    assert any(e["dtr_code"] == "DTR-S1-02" and e["risk"] == "overvoltage" for e in events)
    assert all(e["severity"] in ("warning", "critical") for e in events)


def test_feasibility_endpoint(client, engineer):
    ok = client.post("/api/analytics/feasibility", headers=engineer,
                     json={"dtr_id": dtr_id(client, engineer, "DTR-N2-03"), "kw": 5}).json()
    assert ok["recommendation"] == "clear" and ok["recommended_kw"] == 5
    no = client.post("/api/analytics/feasibility", headers=engineer,
                     json={"dtr_id": dtr_id(client, engineer, "DTR-S1-02"), "kw": 5}).json()
    assert no["recommendation"] == "reject"
    bad = client.post("/api/analytics/feasibility", headers=engineer, json={"dtr_id": 1, "kw": 0})
    assert bad.status_code == 422
