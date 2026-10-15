-- Important queries used by SolarClear (parameters shown as ?)

-- 1. DTR context: rating, feeder, location and installed PV (rolled up from consumers)
SELECT d.id, d.code, d.rating_kva, f.code AS feeder_code, s.latitude, s.longitude,
       COALESCE((SELECT SUM(pv_kw) FROM consumers c WHERE c.dtr_id = d.id), 0) AS pv_kw,
       COALESCE((SELECT SUM(pv_kw) FROM consumers c WHERE c.dtr_id = d.id AND c.scheme = 'kusum'), 0) AS kusum_kw
FROM dtrs d
JOIN feeders f ON f.id = d.feeder_id
JOIN substations s ON s.id = f.substation_id
WHERE d.id = ?;

-- 2. Model training set: last 14 days of DTR readings joined with observed irradiance
SELECT r.ts, r.load_kw, r.solar_kw, r.net_kw, r.voltage_pu, w.ghi_wm2, w.temp_c
FROM readings r
LEFT JOIN weather w ON w.substation_id = ? AND w.kind = 'observed' AND w.ts = r.ts
WHERE r.dtr_id = ?
ORDER BY r.ts DESC
LIMIT 336;

-- 3. Queue ahead of an application (first-come-first-served clearance)
SELECT COALESCE(SUM(requested_kw), 0) AS kw
FROM applications
WHERE dtr_id = ? AND status IN ('pending', 'evaluated') AND id < ?;

-- 4. Solar adoption rate over the last 12 months (for months-to-saturation)
SELECT COALESCE(SUM(pv_kw), 0) / 12.0 AS kw_per_month
FROM consumers
WHERE dtr_id = ? AND pv_kw > 0 AND pv_commissioned_on >= date('now', '-365 days');

-- 5. Cache-aware forecast upsert (Open-Meteo / clear-sky results)
INSERT INTO weather (substation_id, ts, kind, ghi_wm2, temp_c, cloud_pct, source, fetched_at)
VALUES (?, ?, 'forecast', ?, ?, ?, ?, datetime('now'))
ON CONFLICT (substation_id, ts, kind) DO UPDATE SET
    ghi_wm2 = excluded.ghi_wm2, temp_c = excluded.temp_c, cloud_pct = excluded.cloud_pct,
    source = excluded.source, fetched_at = excluded.fetched_at;

-- 6. DTR list with installed PV and consumer count
SELECT d.*, f.code AS feeder_code, COALESCE(SUM(c.pv_kw), 0) AS pv_kw, COUNT(c.id) AS consumer_count
FROM dtrs d
JOIN feeders f ON f.id = d.feeder_id
LEFT JOIN consumers c ON c.dtr_id = d.id
GROUP BY d.id
ORDER BY d.code;

-- 7. Open alerts, most severe first
SELECT a.*, d.code AS dtr_code
FROM alerts a JOIN dtrs d ON d.id = a.dtr_id
WHERE a.acknowledged = 0
ORDER BY CASE a.severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, a.id;

-- 8. Approval: add sanctioned PV to the consumer so hosting capacity updates immediately
UPDATE consumers SET pv_kw = pv_kw + ?, scheme = ?, pv_commissioned_on = date('now') WHERE id = ?;

-- 9. Agent token usage totals
SELECT SUM(prompt_tokens) AS prompt_tokens, SUM(completion_tokens) AS completion_tokens, kind, mode
FROM agent_runs GROUP BY kind, mode;

-- 10. Feeder-level daily solar energy vs export (reporting)
SELECT f.code, substr(r.ts, 1, 10) AS day,
       ROUND(SUM(r.solar_kw), 1) AS solar_kwh,
       ROUND(SUM(CASE WHEN r.net_kw < 0 THEN -r.net_kw ELSE 0 END), 1) AS export_kwh,
       ROUND(MAX(r.voltage_pu), 3) AS max_voltage_pu
FROM readings r JOIN dtrs d ON d.id = r.dtr_id JOIN feeders f ON f.id = d.feeder_id
GROUP BY f.code, day
ORDER BY day DESC, f.code;
