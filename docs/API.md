# SolarClear API reference

Base URL: `http://localhost:8000`. Interactive OpenAPI docs: `/docs`.

**Authentication.** First call `POST /api/auth/login`. Then send `Authorization: Bearer <token>` on every other `/api` route.

**Language.** Send `X-Lang: te` to get Telugu in the copilot answer, the scan summary and the shift brief. Without the header everything is English. Stored text comes back in both languages: `decision_reason` and `decision_reason_te` on applications, `message` and `message_te` on alerts, `reason` and `reason_te` on feasibility checks, and `detail` and `detail_te` on risk events.

**Errors** come back as `{"detail": "..."}` with the HTTP status:

| Status | Meaning |
|---|---|
| 400 | Bad reference |
| 401 | Not authenticated |
| 403 | Wrong role |
| 404 | Not found |
| 409 | Conflict or wrong state |
| 422 | Validation failed; `detail` is a list of field errors |
| 500 | Internal error, logged on the server |

## Auth

| Method | Endpoint | Purpose | Auth |
|---|---|---|---|
| POST | `/api/auth/register` | Create an engineer account | none |
| POST | `/api/auth/login` | Get a token | none |
| GET | `/api/auth/me` | Current user | token |

```http
POST /api/auth/login
{"email": "engineer@solarclear.local", "password": "Engineer@123"}

200 {"token": "eyJzdWIi...", "user": {"id": 2, "name": "Planning Engineer", "email": "...", "role": "engineer"}}
401 {"detail": "Invalid email or password"}
```

Register validation: the name must be 2 to 80 characters. The email must be valid; it is stored in lower case. The password must be at least 8 characters and contain letters and digits.

## Network assets

| Method | Endpoint | Purpose | Auth |
|---|---|---|---|
| GET | `/api/substations` | List substations | token |
| GET | `/api/feeders` | Feeders with their DTR count | token |
| POST | `/api/feeders` | Create a feeder | admin |
| PUT | `/api/feeders/{id}` | Update a feeder | admin |
| DELETE | `/api/feeders/{id}` | Delete a feeder; its DTRs and their data are deleted too | admin |
| GET | `/api/dtrs?feeder_id=` | DTRs with installed PV and consumer count | token |
| GET | `/api/dtrs/{id}` | A DTR with its consumers and the last 48 h of readings | token |
| POST | `/api/dtrs` | Create a DTR | admin |
| PUT | `/api/dtrs/{id}` | Partial update (name, `rating_kva`, `area_type`) | admin |
| DELETE | `/api/dtrs/{id}` | Delete a DTR | admin |

```http
POST /api/dtrs
{"feeder_id": 1, "code": "DTR-N1-05", "name": "N1-05 Urban DTR", "rating_kva": 160, "area_type": "urban"}

201 {"id": 17, "feeder_id": 1, "code": "DTR-N1-05", "rating_kva": 160.0, ...}
409 {"detail": "Code already exists"}
```

## Analytics

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/analytics/overview` | KPIs, limits, hosting capacity for every DTR, and the feeder roll-up |
| GET | `/api/analytics/hosting/dtr/{id}` | Hosting capacity for one DTR, with its learned model |
| GET | `/api/analytics/hosting/feeder/{id}` | A feeder and its DTRs |
| GET | `/api/analytics/forecast/dtr/{id}?hours=48` | Hourly forecast of solar, load, net export and voltage, with risk flags. `hours` must be 1 to 72. |
| GET | `/api/analytics/risks?feeder_id=` | Forecast overvoltage and reverse-flow events |
| GET | `/api/analytics/saturated` | Saturated and watch DTRs, sorted by utilisation |
| POST | `/api/analytics/feasibility` | Net-meter clearance check without saving anything |

```http
GET /api/analytics/hosting/dtr/10

200 {
  "dtr_code": "DTR-S1-02", "feeder_code": "FDR-S1", "rating_kva": 63.0, "consumers": 24,
  "existing_pv_kw": 79.8, "hosting_kw": 0.0, "utilisation_pct": 100.0, "binding_constraint": "voltage",
  "limits_kw": {"reverse_flow": 21.8, "voltage": 0.0, "policy_cap": 0.0},
  "pending_kw": 3.0, "headroom_after_queue_kw": -3.0, "growth_kw_per_month": 2.74,
  "months_to_saturation": 0.0, "status": "saturated",
  "worst_case_now": {"export_kw": 37.9, "voltage_pu": 1.088, "reverse_flow_pct_of_rating": 60.1},
  "model": {"performance_ratio": 0.771, "peak_gen_per_kw": 0.576, "min_midday_load_kw": 8.1,
            "voltage_intercept_pu": 1.0219, "voltage_sensitivity_pu_per_kw": 0.00175, "voltage_fit_r2": 0.991, "samples": 336}
}
```

This is real output from the sample data. The seed is fixed, but the dates are relative to when you seed, so your numbers will be close but not identical.

```http
GET /api/analytics/forecast/dtr/10?hours=48

200 {"dtr_code": "DTR-S1-02", "weather_source": "open-meteo",
     "limits": {"voltage_upper_pu": 1.06, "reverse_flow_kw": 50.4},
     "summary": {"solar_energy_kwh": 639.8, "export_energy_kwh": 416.3, "peak_solar_kw": 47.3,
                 "peak_export_kw": 38.4, "max_voltage_pu": 1.089, "risk_hours": 10},
     "points": [{"ts": "2026-10-15T12:00", "ghi_wm2": 870, "solar_kw": 47.3, "load_kw": 8.9,
                 "net_export_kw": 38.4, "voltage_pu": 1.089, "risks": ["overvoltage"]}, ...]}
```

```http
POST /api/analytics/feasibility
{"dtr_id": 12, "kw": 8, "scheme": "rooftop"}

200 {"recommendation": "partial", "recommended_kw": 5.0, "requested_kw": 8, "headroom_kw": 5.4,
     "queued_ahead_kw": 6.0, "binding_constraint": "voltage",
     "reason": "Partially feasible: only 5.0 kW can be cleared without breaching limits (or sanction 8 kW with export limiting). DTR-S1-04 ..."}
```

## Applications (net-metering and PM-KUSUM)

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/applications?status=` | List applications. `status` is pending, evaluated, approved or rejected. |
| GET | `/api/applications/{id}` | Get one application |
| POST | `/api/applications` | Create. Body: `dtr_id`, `applicant_name`, `scheme` (rooftop or kusum), `requested_kw`, optional `consumer_id`. |
| PUT | `/api/applications/{id}` | Edit an open application. Any edit resets its evaluation. |
| DELETE | `/api/applications/{id}` | Delete. Approved applications can be deleted by admins only. |
| POST | `/api/applications/{id}/evaluate` | Agent clearance. Saves the recommendation and sets status to `evaluated`. |
| POST | `/api/applications/{id}/decision` | `{"decision": "approve" or "reject", "approved_kw"?, "note"?}`. Approving adds the PV to the DTR. |

State rules:

* An application must be evaluated before a decision. Otherwise the call returns 409.
* `approved_kw` cannot be more than `requested_kw`. Otherwise the call returns 400.
* Decided applications cannot be edited. Otherwise the call returns 409.

## Agent and alerts

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/agent/status` | Shows whether the LLM is enabled and the deployment name |
| POST | `/api/agent/chat` | Planning Copilot. Body: `{"message": "...", "history": [{"role": "user" or "assistant", "content": "..."}]}` |
| POST | `/api/agent/scan` | Grid-Watch autonomous scan. Body: `{"with_brief": true}` |
| GET | `/api/agent/runs` | The last 50 agent runs, plus token totals |
| GET | `/api/alerts?include_acknowledged=false` | Alerts, critical first |
| POST | `/api/alerts/{id}/ack` | Acknowledge an alert |
| GET | `/api/health` | Liveness check; no auth needed |

```http
POST /api/agent/chat
{"message": "Can DTR-S1-04 take an 8 kW rooftop system?"}

200 {"answer": "- DTR-S1-04: 8 kW is not fully feasible ... Recommended clearance: 5.0 kW ...",
     "tools_used": ["netmeter_feasibility"], "mode": "d360",
     "usage": {"prompt_tokens": 1385, "completion_tokens": 160}}
```

```http
POST /api/agent/scan
{"with_brief": false}

200 {"summary": "Scanned 16 DTRs: 3 saturated, 2 on watch. 1 forecast risk event(s), 6 alert(s) raised (4 critical), 9 application(s) evaluated.",
     "brief": null, "mode": "offline", "alerts_created": 6, "critical_alerts": 4, "risk_events": 1,
     "applications_evaluated": [{"id": 1, "dtr": "DTR-N1-01", "kw": 5.0, "rec": "clear", "rec_kw": 5.0}, ...],
     "webhook_notified": false, "usage": {"prompt_tokens": 0, "completion_tokens": 0}}
```

### Agent tools

The agent can call these 7 tools. All of them are read-only.

| Tool | Arguments | Returns |
|---|---|---|
| `network_overview` | none | Totals for each feeder |
| `dtr_hosting_capacity` | `dtr_code` | Limits, status, queue and saturation outlook |
| `list_dtrs` | `status?`, `feeder_code?` | Up to 12 DTRs, sorted by utilisation |
| `solar_forecast` | `dtr_code`, `hours?` | Forecast summary, top 3 export hours and risk hours |
| `forecast_risks` | `feeder_code?` | Up to 10 risk events |
| `netmeter_feasibility` | `dtr_code`, `kw`, `scheme?` | Clearance recommendation |
| `list_applications` | `status?` | Up to 15 applications |

## External APIs

| API | Used for | Auth | Request |
|---|---|---|---|
| D360 AI engine | Copilot reasoning and the scan brief | `api-key` header from `D360_AI_API_KEY` | `POST {D360_AI_ENDPOINT}` with `messages`, `tools`, `max_completion_tokens` and `reasoning_effort` |
| Open-Meteo Forecast | Hourly GHI, temperature and cloud cover | none | `GET https://api.open-meteo.com/v1/forecast?latitude=..&longitude=..&hourly=shortwave_radiation,temperature_2m,cloud_cover&forecast_days=3&timezone=Asia/Kolkata`. Cached in the `weather` table for 3 hours. |
| Webhook (optional) | Critical alert notifications | URL secret | `POST NOTIFY_WEBHOOK_URL {"text": "..."}` |
