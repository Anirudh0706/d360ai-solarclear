# Testing evidence

**How to run:** `python -m pytest -v` (from the project root)

**Environment:**

* The tests run fully offline. `WEATHER_PROVIDER=clearsky` is set, and the D360 AI key is blanked.
* The D360 AI tool-calling loop is tested with a fake engine, and the HTTPS client is tested with a stubbed network.
* Each test module gets a fresh SQLite database with the seeded sample data.

**Latest run:** 67 passed, 0 failed, in 5.4 s (Python 3.12.10, Windows 11).

## Test cases

### Authentication and authorization ([tests/test_auth.py](../tests/test_auth.py))

| # | Test case | Expected result | Actual result | Status |
|---|---|---|---|---|
| 1 | Login with valid credentials | 200, token and role returned | 200, token, role `engineer` | Pass |
| 2 | Login with invalid password | 401 "Invalid email or password" | 401 with that message | Pass |
| 3 | Login with an unknown email | 401 | 401 | Pass |
| 4 | Register a new user, then call `/me` with the token | 201; email normalised; role is engineer; `/me` works | As expected | Pass |
| 5 | Register with an email that already exists | 409 | 409 | Pass |
| 6 | Register with a weak password, a password with no digits, or a bad email | 422 for each | 422 for each | Pass |
| 7 | Call a protected route with no token | 401 | 401 | Pass |
| 8 | Call with a tampered token signature | 401 | 401 | Pass |
| 9 | Engineer tries to create a feeder | 403, admin only | 403 | Pass |

### Database and CRUD ([tests/test_assets.py](../tests/test_assets.py))

| # | Test case | Expected result | Actual result | Status |
|---|---|---|---|---|
| 10 | Sample data loaded | 4 feeders and 16 DTRs, 4 DTRs per feeder | As expected | Pass |
| 11 | DTR detail | Includes consumers and 48 readings | As expected | Pass |
| 12 | Create, update and delete a DTR | 201 with the code upper-cased, then 200, then 204, then 404 | As expected | Pass |
| 13 | Create a DTR with a duplicate code | 409, UNIQUE constraint | 409 | Pass |
| 14 | Create a DTR with a feeder that does not exist | 400, FOREIGN KEY constraint | 400 | Pass |
| 15 | Create a DTR with a negative kVA or an invalid code | 422 | 422 | Pass |
| 16 | Delete a feeder that has DTRs | 204; its DTRs are deleted too (ON DELETE CASCADE) | As expected | Pass |
| 17 | Raise a DTR's kVA (augmentation) | Hosting capacity increases | Increased | Pass |

### Forecasting, hosting capacity and risk ([tests/test_analytics.py](../tests/test_analytics.py))

| # | Test case | Expected result | Actual result | Status |
|---|---|---|---|---|
| 18 | Clear-sky irradiance at noon and at night | 750 to 1050 W/mÂ² at noon, 0 at night | As expected | Pass |
| 19 | PV temperature derating | Hot output < cool output â‰¤ rating; 0 output at 0 irradiance | As expected | Pass |
| 20 | Least-squares fit on a known line | Recovers a, b and RÂ² = 1 | As expected | Pass |
| 21 | Voltage sensitivity learned from meter data | Within 20% of the seeded true value (0.0007 pu/kW); RÂ² > 0.6 | As expected | Pass |
| 22 | Over-penetrated rural DTR (S1-02) | Status `saturated`, 0 kW headroom, voltage-bound | As expected | Pass |
| 23 | Lightly loaded DTR (N2-03) | Status `available`, more than 50 kW headroom, equal to the smallest limit | As expected | Pass |
| 24 | Overview: feeder hosting compared with the sum of its DTRs | Feeder hosting â‰¤ sum of its DTRs; 2 or more saturated | As expected | Pass |
| 25 | Saturated list | Only saturated and watch DTRs, sorted by utilisation in descending order | As expected | Pass |
| 26 | 48-hour forecast physics | 48 points; solar â‰¥ 0; export = solar âˆ’ load; no solar at night | As expected | Pass |
| 27 | Forecast with an unknown DTR, or `hours=500` | 404 and 422 | 404 and 422 | Pass |
| 28 | Risk detection | Overvoltage event for DTR-S1-02 | Detected | Pass |
| 29 | Feasibility check | 5 kW on N2-03 â†’ clear; 5 kW on S1-02 â†’ reject; 0 kW â†’ 422 | As expected | Pass |

### Application workflow ([tests/test_applications.py](../tests/test_applications.py))

| # | Test case | Expected result | Actual result | Status |
|---|---|---|---|---|
| 30 | Submit and evaluate an application | Saved as pending; agent result is `clear`; status becomes `evaluated` | As expected | Pass |
| 31 | Application on a saturated DTR | `reject`, 0 kW | As expected | Pass |
| 32 | Request larger than headroom | `partial` or `reject`; recommended kW â‰¤ headroom | As expected | Pass |
| 33 | Two applications competing for the same headroom | First is `clear`; second is limited by the queue ahead of it | As expected | Pass |
| 34 | Approve an application | PV is added to the DTR; hosting capacity falls; consumer is created | As expected | Pass |
| 35 | Decide before evaluating | 409 | 409 | Pass |
| 36 | Approve more kW than requested | 400 | 400 | Pass |
| 37 | Reject with a note | Status `rejected`; the note is saved | As expected | Pass |
| 38 | Edit an evaluated application, then delete it | Evaluation is reset; delete returns 204, then 404 | As expected | Pass |
| 39 | Negative kW, unknown DTR, or invalid scheme | 422, 400 and 422 | As expected | Pass |
| 40 | Filter applications by status | Only approved applications returned | As expected | Pass |

### Agent ([tests/test_agent.py](../tests/test_agent.py))

| # | Test case | Expected result | Actual result | Status |
|---|---|---|---|---|
| 41 | Offline: feasibility question | Routes to `netmeter_feasibility`; answers CLEAR | As expected | Pass |
| 42 | Offline: forecast question with free-form DTR text ("dtr s1 02") | Routes to `solar_forecast` | As expected | Pass |
| 43 | Offline: saturation question and a general question | `list_dtrs` and `network_overview` | As expected | Pass |
| 44 | Unknown DTR code | Polite "Unknown DTR" answer, not a crash | As expected | Pass |
| 45 | Empty chat message | 422 | 422 | Pass |
| 46 | Grid-Watch scan | Alerts raised, including a critical one; all pending applications evaluated; 0 tokens used | As expected | Pass |
| 47 | Run the scan twice | Alert count is unchanged (no duplicates) | As expected | Pass |
| 48 | Acknowledge an alert, then acknowledge an unknown alert | Removed from the open list; unknown alert returns 404 | As expected | Pass |
| 49 | Agent runs logged | Both chat and scan runs appear in the audit log | As expected | Pass |
| 50 | D360 AI loop (fake engine) | Tool called, answer uses the tool result, tokens summed (200/40), compact tool payload | As expected | Pass |
| 51 | D360 AI engine fails (network error) | Falls back to offline mode with a notice | As expected | Pass |
| 52 | Scan with an AI brief | Exactly 1 LLM call | As expected | Pass |
| 53 | Bad tool arguments (text kW, negative kW, unknown feeder, unknown tool) | Error returned as data | As expected | Pass |

### English and Telugu ([tests/test_i18n.py](../tests/test_i18n.py))

| # | Test case | Expected result | Actual result | Status |
|---|---|---|---|---|
| 54 | The English and Telugu UI files have the same keys | No key missing from Telugu | None missing | Pass |
| 55 | Every `t("key")` in `app.js` and every `data-i18n` in `index.html` | Each key exists in both languages | All exist | Pass |
| 56 | Telugu UI text for key labels | Written in Telugu script | As expected | Pass |
| 57 | Every server message template | Has both an English and a Telugu version | As expected | Pass |
| 58 | Feasibility check on a saturated DTR | English reason and Telugu `reason_te`, both containing the DTR code | As expected | Pass |
| 59 | Application whose applicant name is in Telugu (à°°à°®à±‡à°·à±) | Name is saved and read back correctly; reason stored in both languages | As expected | Pass |
| 60 | Grid-Watch scan with `X-Lang: te` | Summary in Telugu; every alert has a Telugu message | As expected | Pass |
| 61 | Offline copilot asked a Telugu question about kW on a DTR | Uses the feasibility tool; answer in Telugu ("à°…à°¨à±à°®à°¤à°¿à°‚à°šà°µà°šà±à°šà±") | As expected | Pass |
| 62 | Telugu keywords such as à°¸à°‚à°¤à±ƒà°ªà±à°¤ (saturated) and à°µà±‹à°²à±à°Ÿà±‡à°œà± à°ªà±à°°à°®à°¾à°¦à°‚ (voltage risk) | Routed to the right tool | As expected | Pass |
| 63 | Request with no language header | Answer in English | English | Pass |
| 64 | Message formatting with a translated word and an unknown language | Telugu text produced; unknown language falls back to English | As expected | Pass |

## Manual and integration testing

These checks ran against the live server (`uvicorn`), with the real D360 AI engine and the real Open-Meteo API.

| Check | Result |
|---|---|
| UI page and static assets load | 200 |
| Overview for 16 DTRs | 0.37 s |
| Forecast for DTR-S1-02 using Open-Meteo | `weather_source: open-meteo`; 10 overvoltage risk hours; peak 1.089 pu |
| Grid-Watch scan without a brief | 1.6 s: 3 saturated, 6 alerts, 9 applications evaluated |
| Grid-Watch scan with a D360 AI brief | 537 prompt + 211 completion tokens. Prioritised 4-bullet brief naming DTR-S1-02, N1-03 and S1-04. |
| Copilot: "Can I connect 8 kW rooftop on DTR-S1-04?" | Called `netmeter_feasibility`; answered *partial, 5.0 kW, voltage-bound*. 1,385 + 160 tokens. |
| Copilot: "Which DTRs are saturated on feeder S1?" | Called `list_dtrs` twice; correct list. 1,477 + 256 tokens. |
| Telugu scan with brief (`X-Lang: te`) | Summary, alerts and a 4-bullet brief, all in Telugu. 336 + 354 tokens. |
| Telugu copilot: "DTR-S1-04 à°•à°¿ 8 kW à°°à±‚à°«à±â€Œà°Ÿà°¾à°ªà± à°¸à°¿à°¸à±à°Ÿà°®à± à°•à°²à°ªà°µà°šà±à°šà°¾?" ("Can an 8 kW rooftop system be added on DTR-S1-04?") | Called `dtr_hosting_capacity` and `netmeter_feasibility`; answered in Telugu: not feasible, voltage-bound. |
| Copilot: "How much more KUSUM solar can feeder S2 absorb?" | Called `network_overview`; answered 388.5 kW headroom. 1,510 + 150 tokens. |

## Bugs identified

| # | Bug | How it was found | Fix | Retest |
|---|---|---|---|---|
| B1 | The asset-code validator was attached as `_v_code = field_validator(...)`. Pydantic treats underscore names as private attributes, so the validator never ran and invalid codes were accepted. | Code review before the first run | Rewrote it as an explicit `@field_validator` method on `FeederIn` and `DtrIn` | Test 15 passes |
| B2 | The `status` query parameter on `GET /api/applications` shadowed the imported `fastapi.status` module. | Code review | Renamed the parameter to `status_filter`, with `Query(alias="status")` | Test 40 passes |
| B3 | Risk detection found no overvoltage in offline mode. The seed gave small DTRs too few consumers to reach their target PV penetration, so DTR-S1-02 stayed below the 1.06 pu limit. | Test 28 failed on the first run | Set a minimum of 24 consumers per DTR in the seed and raised S1-02 to a legacy over-sanctioned 125% | 53/53 pass |
| B4 | `.env` written by PowerShell has a UTF-8 BOM, which would corrupt the first key name. | Review of the env loader | The loader now reads `.env` with `utf-8-sig` | Server starts with the D360 AI engine enabled |
| B5 | `datetime.utcnow()` is deprecated in Python 3.12, so the forecast cache produced a warning. | Code review | Switched to timezone-aware `datetime.now(timezone.utc)` | Warning gone |

## Retesting performed

The full suite was re-run after each fix: 52/53 passed before the B3 fix and 53/53 after. The live end-to-end check with the D360 AI engine and Open-Meteo was repeated after the final seed change.

## Remaining issues and limitations

* The sample data is synthetic. The models need real DT-meter or AMI data before field decisions are made.
* Load is forecast as the 7-day mean for each hour of day. Weekdays, holidays and seasonal effects are not modelled.
* The voltage model is linear and covers each DTR separately. It does not model voltage interaction between DTRs on a feeder or tap changes, so borderline cases still need a power-flow study.
* SQLite allows only one writer at a time, which suits a pilot. For many concurrent users, move to PostgreSQL; the SQL is portable.
* There is no login rate limiting, and the UI keeps the token in localStorage. Add rate limiting and httpOnly cookies before production.
* The UI was checked by loading the page and calling the API. There are no automated browser tests.
