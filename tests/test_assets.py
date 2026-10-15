"""CRUD on feeders and DTRs, database constraints and validation."""
from tests.conftest import dtr_id


def test_seed_data_loaded(client, engineer):
    feeders = client.get("/api/feeders", headers=engineer).json()
    dtrs = client.get("/api/dtrs", headers=engineer).json()
    assert len(feeders) == 4 and len(dtrs) == 16
    assert all(f["dtr_count"] == 4 for f in feeders)


def test_dtr_detail_includes_consumers_and_readings(client, engineer):
    detail = client.get(f"/api/dtrs/{dtr_id(client, engineer, 'DTR-N1-03')}", headers=engineer).json()
    assert detail["consumers"] and len(detail["recent_readings"]) == 48
    assert sum(c["pv_kw"] for c in detail["consumers"]) > 80


def test_create_update_delete_dtr(client, admin):
    created = client.post("/api/dtrs", headers=admin,
                          json={"feeder_id": 1, "code": "dtr-n1-09", "name": "Test DTR", "rating_kva": 100})
    assert created.status_code == 201
    new_id = created.json()["id"]
    assert created.json()["code"] == "DTR-N1-09"  # normalised to upper case

    updated = client.put(f"/api/dtrs/{new_id}", headers=admin, json={"rating_kva": 160})
    assert updated.status_code == 200 and updated.json()["rating_kva"] == 160

    assert client.delete(f"/api/dtrs/{new_id}", headers=admin).status_code == 204
    assert client.get(f"/api/dtrs/{new_id}", headers=admin).status_code == 404


def test_duplicate_code_conflict(client, admin):
    res = client.post("/api/dtrs", headers=admin, json={"feeder_id": 1, "code": "DTR-N1-01", "name": "Dup", "rating_kva": 100})
    assert res.status_code == 409


def test_invalid_foreign_key(client, admin):
    res = client.post("/api/dtrs", headers=admin, json={"feeder_id": 999, "code": "DTR-Z1-01", "name": "Orphan", "rating_kva": 100})
    assert res.status_code == 400


def test_dtr_validation(client, admin):
    bad_rating = client.post("/api/dtrs", headers=admin, json={"feeder_id": 1, "code": "DTR-Q1", "name": "Bad", "rating_kva": -5})
    assert bad_rating.status_code == 422
    bad_code = client.post("/api/dtrs", headers=admin, json={"feeder_id": 1, "code": "bad code!", "name": "Bad", "rating_kva": 100})
    assert bad_code.status_code == 422


def test_feeder_crud_cascades(client, admin):
    feeder = client.post("/api/feeders", headers=admin,
                         json={"substation_id": 1, "code": "FDR-T9", "name": "Temp feeder", "rating_kva": 2000}).json()
    dtr = client.post("/api/dtrs", headers=admin,
                      json={"feeder_id": feeder["id"], "code": "DTR-T9-01", "name": "Temp", "rating_kva": 63}).json()
    assert client.delete(f"/api/feeders/{feeder['id']}", headers=admin).status_code == 204
    assert client.get(f"/api/dtrs/{dtr['id']}", headers=admin).status_code == 404  # ON DELETE CASCADE


def test_dtr_augmentation_increases_hosting(client, admin):
    target = dtr_id(client, admin, "DTR-N1-03")
    before = client.get(f"/api/analytics/hosting/dtr/{target}", headers=admin).json()
    client.put(f"/api/dtrs/{target}", headers=admin, json={"rating_kva": 160})
    after = client.get(f"/api/analytics/hosting/dtr/{target}", headers=admin).json()
    client.put(f"/api/dtrs/{target}", headers=admin, json={"rating_kva": before["rating_kva"]})  # restore
    assert after["hosting_kw"] > before["hosting_kw"]
