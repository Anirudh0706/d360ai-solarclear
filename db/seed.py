"""Synthetic but physically consistent sample data for SolarClear.

Creates 2 substations, 4 feeders, 16 DTRs, ~500 consumers, 14 days of hourly
weather + DTR meter readings, pending applications and two demo users.

    python -m db.seed           # seed only if the database is empty
    python -m db.seed --reset   # wipe and re-seed
"""
import argparse
import math
import os
import random
import sqlite3
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.analytics.solar import cell_temperature_derate, clearsky_ghi  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import connect, init_db  # noqa: E402
from app.security import hash_password  # noqa: E402

TS_FMT = "%Y-%m-%dT%H:00"

SUBSTATIONS = [
    ("SS-NORTH", "North 33/11 kV Substation", 17.45, 78.38),
    ("SS-SOUTH", "South 33/11 kV Substation", 17.24, 78.43),
]
FEEDERS = [  # code, name, substation, rating kVA
    ("FDR-N1", "N1 Residential Feeder", "SS-NORTH", 4000),
    ("FDR-N2", "N2 Commercial Feeder", "SS-NORTH", 4000),
    ("FDR-S1", "S1 Rural Mixed Feeder", "SS-SOUTH", 3000),
    ("FDR-S2", "S2 Agricultural (KUSUM) Feeder", "SS-SOUTH", 3000),
]
DTRS = [  # code, feeder, kVA, area, PV penetration (share of kVA)
    ("DTR-N1-01", "FDR-N1", 100, "urban", 0.15), ("DTR-N1-02", "FDR-N1", 160, "urban", 0.55),
    ("DTR-N1-03", "FDR-N1", 100, "urban", 0.92), ("DTR-N1-04", "FDR-N1", 250, "urban", 0.30),
    ("DTR-N2-01", "FDR-N2", 250, "urban", 0.35), ("DTR-N2-02", "FDR-N2", 160, "urban", 0.70),
    ("DTR-N2-03", "FDR-N2", 100, "urban", 0.08), ("DTR-N2-04", "FDR-N2", 63, "urban", 0.60),
    ("DTR-S1-01", "FDR-S1", 100, "rural", 0.45), ("DTR-S1-02", "FDR-S1", 63, "rural", 1.25),  # legacy over-sanctioned DTR
    ("DTR-S1-03", "FDR-S1", 100, "rural", 0.20), ("DTR-S1-04", "FDR-S1", 160, "rural", 0.80),
    ("DTR-S2-01", "FDR-S2", 250, "agri", 0.40), ("DTR-S2-02", "FDR-S2", 160, "agri", 0.75),
    ("DTR-S2-03", "FDR-S2", 100, "agri", 0.10), ("DTR-S2-04", "FDR-S2", 250, "agri", 0.55),
]
# Load shape (share of base load) per hour 0..23, by area type.
LOAD_SHAPE = {
    "urban": [.50, .45, .42, .40, .42, .50, .65, .80, .78, .65, .58, .55, .55, .55, .56, .60, .70, .85, 1.0, 1.0, .95, .85, .70, .58],
    "rural": [.45, .40, .38, .38, .42, .55, .70, .72, .60, .48, .40, .38, .38, .38, .40, .45, .60, .85, 1.0, .95, .85, .70, .55, .48],
    "agri":  [.30, .28, .28, .28, .30, .45, .70, .80, .85, .85, .80, .75, .70, .70, .72, .75, .70, .60, .55, .50, .45, .40, .35, .32],
}
LOAD_FACTOR = {"urban": 0.45, "rural": 0.35, "agri": 0.40}
VOLTAGE_SENSITIVITY = {"urban": 0.07, "rural": 0.11, "agri": 0.09}  # pu per (kW/kVA)
NAMES = ["Rao", "Reddy", "Sharma", "Naidu", "Kumar", "Devi", "Goud", "Prasad", "Khan", "Varma", "Patel", "Iyer"]


def seed(conn: sqlite3.Connection, days: int = 14, rng_seed: int = 42) -> None:
    rng = random.Random(rng_seed)
    init_db(conn)

    conn.executemany(
        "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
        [("Grid Admin", "admin@solarclear.local", hash_password("Admin@123"), "admin"),
         ("Planning Engineer", "engineer@solarclear.local", hash_password("Engineer@123"), "engineer")],
    )
    sub_ids = {}
    for code, name, lat, lon in SUBSTATIONS:
        sub_ids[code] = conn.execute(
            "INSERT INTO substations (code, name, latitude, longitude) VALUES (?, ?, ?, ?)", (code, name, lat, lon)
        ).lastrowid
    feeder_ids, feeder_sub = {}, {}
    for code, name, sub, rating in FEEDERS:
        feeder_ids[code] = conn.execute(
            "INSERT INTO feeders (substation_id, code, name, rating_kva) VALUES (?, ?, ?, ?)",
            (sub_ids[sub], code, name, rating),
        ).lastrowid
        feeder_sub[code] = sub

    # Observed weather per substation: clear-sky x daily clearness x hourly noise.
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    start = now - timedelta(days=days)
    weather = {}
    for code, _, lat, lon in SUBSTATIONS:
        day_k = {}
        for i in range(days * 24):
            ts = start + timedelta(hours=i)
            k = day_k.setdefault(ts.date(), rng.uniform(0.55, 0.95))
            ghi = clearsky_ghi(ts, lat, lon) * k * rng.uniform(0.92, 1.05)
            temp = 22 + 9 * max(0.0, math.sin(math.pi * (ts.hour - 7) / 14)) + rng.uniform(-1, 1)
            weather[(code, ts)] = (ghi, temp)
        conn.executemany(
            "INSERT INTO weather (substation_id, ts, kind, ghi_wm2, temp_c, cloud_pct, source) "
            "VALUES (?, ?, 'observed', ?, ?, NULL, 'meter-site')",
            [(sub_ids[c], ts.strftime(TS_FMT), round(g, 1), round(t, 1)) for (c, ts), (g, t) in weather.items() if c == code],
        )

    account = 100000
    for code, feeder, kva, area, penetration in DTRS:
        dtr_id = conn.execute(
            "INSERT INTO dtrs (feeder_id, code, name, rating_kva, area_type) VALUES (?, ?, ?, ?, ?)",
            (feeder_ids[feeder], code, f"{code.split('-', 1)[1]} {area.title()} DTR", kva, area),
        ).lastrowid

        # Consumers, with PV installed on a random subset until the target penetration is reached.
        n_consumers = max(24, int(kva / 4))
        category = {"urban": "domestic", "rural": "domestic", "agri": "agricultural"}[area]
        consumers = []
        for i in range(n_consumers):
            account += 1
            cat = "commercial" if area == "urban" and i % 7 == 0 else category
            consumers.append([dtr_id, f"AC{account}", f"{rng.choice(NAMES)} {chr(65 + i % 26)}.", cat,
                              round(rng.uniform(2, 15 if cat != "domestic" else 6), 1), 0.0, "none", None])
        target, installed = penetration * kva, 0.0
        for c in rng.sample(consumers, len(consumers)):
            if installed >= target:
                break
            size = min(round(rng.uniform(5, 12) if c[3] != "domestic" else rng.uniform(2, 5), 1), target - installed + 1)
            age_days = int(1095 * rng.random() ** 1.8)  # skewed towards recent installs
            c[5], c[6] = round(size, 1), "kusum" if area == "agri" else "rooftop"
            c[7] = (now - timedelta(days=age_days)).date().isoformat()
            installed += size
        conn.executemany(
            "INSERT INTO consumers (dtr_id, account_no, name, category, sanctioned_load_kw, pv_kw, scheme, "
            "pv_commissioned_on) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", consumers,
        )

        # Hourly meter readings consistent with weather, PV and LV voltage physics.
        pr = rng.uniform(0.74, 0.82)
        base = kva * LOAD_FACTOR[area]
        v0 = rng.uniform(1.015, 1.03)
        sens = VOLTAGE_SENSITIVITY[area] / kva
        readings, day_factor = [], {}
        for i in range(days * 24):
            ts = start + timedelta(hours=i)
            ghi, temp = weather[(feeder_sub[feeder], ts)]
            solar = installed * ghi / 1000 * pr * cell_temperature_derate(ghi, temp) if ghi > 0 else 0.0
            df = day_factor.setdefault(ts.date(), rng.uniform(0.9, 1.1))
            load = base * LOAD_SHAPE[area][ts.hour] * df * rng.uniform(0.95, 1.05)
            voltage = v0 + sens * (solar - load) + rng.gauss(0, 0.003)
            readings.append((dtr_id, ts.strftime(TS_FMT), round(load, 2), round(solar, 2),
                             round(load - solar, 2), round(voltage, 4)))
        conn.executemany(
            "INSERT INTO readings (dtr_id, ts, load_kw, solar_kw, net_kw, voltage_pu) VALUES (?, ?, ?, ?, ?, ?)",
            readings,
        )

    # Pending net-meter / KUSUM applications awaiting clearance.
    apps = [("DTR-N1-01", "S. Rao", "rooftop", 5), ("DTR-N1-03", "K. Reddy", "rooftop", 4),
            ("DTR-N1-02", "Sunrise Apartments", "rooftop", 25), ("DTR-N2-03", "City Mall", "rooftop", 40),
            ("DTR-S1-02", "P. Goud", "rooftop", 3), ("DTR-S1-04", "M. Devi", "rooftop", 6),
            ("DTR-S2-02", "Farmer Group A", "kusum", 15), ("DTR-S2-03", "R. Naidu (pump)", "kusum", 7.5),
            ("DTR-N2-02", "A. Sharma", "rooftop", 10)]
    for code, applicant, scheme, kw in apps:
        dtr_id = conn.execute("SELECT id FROM dtrs WHERE code = ?", (code,)).fetchone()[0]
        conn.execute(
            "INSERT INTO applications (dtr_id, applicant_name, scheme, requested_kw, created_by) VALUES (?, ?, ?, ?, 2)",
            (dtr_id, applicant, scheme, kw),
        )
    conn.commit()


def is_seeded(conn: sqlite3.Connection) -> bool:
    try:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0
    except sqlite3.OperationalError:
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed the SolarClear database")
    parser.add_argument("--reset", action="store_true", help="delete the database file first")
    args = parser.parse_args()
    if args.reset and os.path.exists(settings.database_path):
        os.remove(settings.database_path)
    connection = connect()
    if is_seeded(connection):
        print("Database already seeded:", settings.database_path)
    else:
        seed(connection)
        print("Seeded", settings.database_path)
