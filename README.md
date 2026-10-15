# SolarClear: Agentic Solar Hosting-Capacity & Net-Meter Clearance

SolarClear helps a power distribution utility (DISCOM) decide where rooftop and PM-KUSUM solar can connect. It covers four tasks:

1. **Solar generation and net-export forecasting.** It gives a 48-hour forecast for every distribution transformer (DTR). The forecast combines a live weather forecast with a PV model learned from each DTR's own meter data.
2. **Feeder and DTR hosting-capacity assessment.** It works out how much more solar each DTR and each 11 kV feeder can take before something breaks.
3. **Voltage and reverse-flow risk detection.** It flags forecast hours where voltage goes above the limit or reverse power flow is too high.
4. **Identification of saturated DTRs.** It flags DTRs that are already saturated, and projects when others will saturate given the adoption trend and the application queue.

Net-meter feasibility is usually a manual engineering judgement. SolarClear turns it into a **data-driven clearance**. An AI agent evaluates each application against live hosting capacity, in first-come-first-served order. It recommends **clear**, **partial** or **reject** and gives the numbers behind that. An engineer then approves or rejects.

---

## Features

| Area | What it does |
|---|---|
| Authentication | Register and log in. Passwords are hashed with PBKDF2-SHA256. Sessions use HMAC-signed bearer tokens with an expiry. |
| Authorization | Two roles. `admin` manages network assets. `engineer` evaluates and decides applications. Self-registration always creates an `engineer`. |
| Dashboard | KPIs, a summary card per feeder, and every DTR ranked by utilisation with its status: available, watch or saturated. |
| DTR page | Three hosting limits (reverse flow, voltage, policy cap) with the binding one marked. Shows the learned model parameters, a 48-hour power and voltage forecast with hover tooltips and a data table, a feasibility checker, and the consumer list. |
| Applications (CRUD) | Create, evaluate (agent), edit, approve or reject (engineer), and delete. Approving an application adds its PV to the DTR, so hosting capacity updates immediately. |
| Grid-Watch agent | Autonomous scan. Forecasts every DTR, raises alerts, evaluates every pending application, pushes critical alerts to a webhook, and can optionally write an AI shift brief. |
| D360 AI Copilot | Chat agent on the D360 AI engine with tool calling over the analytics engine. It answers questions such as "Can DTR-S1-04 take 8 kW?" using real computed numbers. |
| Alerts | Overvoltage, reverse-flow, saturation and pipeline alerts, each with a severity. Alerts can be acknowledged. |
| Network assets (CRUD) | Admins add, upgrade (change kVA) and delete feeders and DTRs. Upgrading a DTR raises its hosting capacity straight away. |
| Agent log | Audit trail of every agent run: tools used and tokens spent. |
| English and Telugu (à°¤à±†à°²à±à°—à±) | A one-click language switch on the login screen and in the sidebar. See the "Languages" section below. |
| Offline mode | Without a D360 AI key, a rule-based router answers through the same tools. Without internet access, a clear-sky weather model replaces Open-Meteo. |

## Technology stack

| Layer | Choice | Why |
|---|---|---|
| Backend | Python 3.11+ with FastAPI and Uvicorn | Small and fast, and it generates OpenAPI docs automatically at `/docs`. |
| Database | SQLite through the standard-library `sqlite3` module | No server to install. The schema is plain SQL in [db/schema.sql](db/schema.sql). |
| Analytics | Pure Python (sun position, PV model, least-squares fit, percentiles) | No numpy or pandas, so installs are tiny. |
| AI agent | D360 AI engine (chat completions with tool calling) over plain HTTPS | No vendor SDK; one `httpx` call per step. |
| External API | [Open-Meteo](https://open-meteo.com) hourly irradiance and temperature forecast | Free and needs no key. A clear-sky model is used as fallback. |
| Frontend | One HTML page with vanilla JS and CSS, charts drawn in hand-written SVG | No build step and no CDN. Supports light and dark themes and works on mobile. |
| Tests | pytest with FastAPI TestClient | 67 tests that run offline in about 6 seconds. |

## Project structure

```
solarclear/
â”œâ”€â”€ app/
â”‚   â”œâ”€â”€ main.py              # FastAPI app, startup (schema + seed), static UI
â”‚   â”œâ”€â”€ config.py            # env / .env settings, grid planning limits
â”‚   â”œâ”€â”€ database.py          # sqlite connection + helpers
â”‚   â”œâ”€â”€ security.py          # password hashing, tokens, auth dependencies
â”‚   â”œâ”€â”€ schemas.py           # request validation (pydantic)
â”‚   â”œâ”€â”€ analytics/
â”‚   â”‚   â”œâ”€â”€ solar.py         # sun position, clear-sky GHI, PV output, regression
â”‚   â”‚   â””â”€â”€ grid.py          # forecasting, hosting capacity, risks, feasibility
â”‚   â”œâ”€â”€ agent/
â”‚   â”‚   â”œâ”€â”€ llm.py           # D360 AI engine client (token-capped)
â”‚   â”‚   â”œâ”€â”€ tools.py         # 7 read-only tools exposed to the agent
â”‚   â”‚   â”œâ”€â”€ copilot.py       # tool-calling chat loop + offline router
â”‚   â”‚   â””â”€â”€ gridwatch.py     # autonomous scan agent
â”‚   â”œâ”€â”€ services/
â”‚   â”‚   â”œâ”€â”€ weather.py       # Open-Meteo client + clear-sky fallback + cache
â”‚   â”‚   â”œâ”€â”€ clearance.py     # evaluate / approve applications
â”‚   â”‚   â””â”€â”€ notify.py        # webhook notifications
â”‚   â””â”€â”€ routers/             # auth, assets, analytics, applications, agent
â”œâ”€â”€ db/
â”‚   â”œâ”€â”€ schema.sql           # tables, keys, constraints, indexes
â”‚   â”œâ”€â”€ seed.py              # synthetic but physically consistent sample data
â”‚   â””â”€â”€ queries.sql          # important queries used by the app
â”œâ”€â”€ static/                  # index.html, app.js, styles.css
â”œâ”€â”€ tests/                   # pytest suite
â”œâ”€â”€ docs/
â”‚   â”œâ”€â”€ API.md               # endpoint reference
â”‚   â””â”€â”€ TESTING.md           # test cases, results, bugs
â”œâ”€â”€ .env.example
â””â”€â”€ requirements.txt
```

## Installation

You need Python 3.11 or newer.

```bash
git clone <your-repo-url> solarclear
cd solarclear
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # Windows: copy .env.example .env
```

## Configuration and environment variables

Edit `.env`. It is gitignored, so keys never reach the repository. Every value is optional; without the D360 AI values the app runs in offline mode.

| Variable | Default | Purpose |
|---|---|---|
| `D360_AI_API_KEY` | none | D360 AI engine key. It is sent in the `api-key` header. |
| `D360_AI_ENDPOINT` | none | The full chat-completions URL of your D360 AI endpoint. |
| `AGENT_MAX_COMPLETION_TOKENS` | `2500` | Hard cap on output tokens for each model call. |
| `AGENT_REASONING_EFFORT` | `low` | Reasoning depth of the D360 AI engine. Leave it empty to omit the parameter. |
| `SECRET_KEY` | dev key | Signs session tokens. **Set a long random value.** |
| `TOKEN_TTL_HOURS` | `12` | How long a session lasts. |
| `DATABASE_PATH` | `solarclear.db` | Location of the SQLite file. |
| `VOLTAGE_UPPER_PU` | `1.06` | Upper LV voltage limit, in per-unit. |
| `REVERSE_FLOW_LIMIT_PCT` | `80` | Maximum reverse power flow, as a % of DTR kVA. |
| `POLICY_CAP_PCT` | `100` | Regulatory cap on cumulative solar per DTR, as a % of kVA. |
| `PV_PERFORMANCE_RATIO` | `0.78` | PR used when a DTR has too little data to calibrate its own. |
| `WEATHER_PROVIDER` | `open-meteo` | `open-meteo` for the live forecast, `clearsky` for offline. |
| `NOTIFY_WEBHOOK_URL` | none | Teams, Slack or other webhook that receives critical alerts. |

## Database setup

The database sets itself up. On first start the app runs [db/schema.sql](db/schema.sql) and loads sample data. To reset it:

```bash
python -m db.seed --reset
```

The sample data contains:

* The network is set in real **Telangana** localities around Hyderabad. Names are given in both English and Telugu. The electrical data is synthetic.

  | Substation | Feeder | DTR localities |
  |---|---|---|
  | 33/11 kV Kompally (Medchal-Malkajgiri) | FDR-N1 Kompally Residential | Kompally Main Road, Dulapally, Pet Basheerabad, Gundlapochampally |
  | | FDR-N2 Suchitra-Jeedimetla Commercial | Suchitra Circle, Jeedimetla, Shapur Nagar, Chintal |
  | 33/11 kV Shadnagar (Ranga Reddy) | FDR-S1 Shadnagar Rural | Shadnagar Town, Farooqnagar, Kondurg, Chowdergudem |
  | | FDR-S2 Kothur Agricultural (PM-KUSUM) | Kothur, Nandigama, Keshampet, Talakondapalle |

  Substation coordinates are real, so the live Open-Meteo forecast is for those places. You can name a DTR by locality anywhere a code is accepted, for example "hosting capacity at Pet Basheerabad" or "à°«à°°à±‚à°–à±â€Œà°¨à°—à°°à± à°²à±‹ 3 kW à°•à°²à°ªà°µà°šà±à°šà°¾?" ("Can 3 kW be added at Farooqnagar?").
* 16 DTRs of 63 to 250 kVA.
* About 600 consumers. Rooftop or KUSUM PV is installed at penetrations from 8% to 125% of DTR kVA, and commissioning dates are spread over 3 years.
* 14 days of hourly weather and DTR meter readings (load, solar, net flow and voltage), about 5,400 rows. The data is generated from the same physics the analytics use, plus noise.
* 9 pending applications and two users:

| Role | Email | Password |
|---|---|---|
| admin | `admin@solarclear.local` | `Admin@123` |
| engineer | `engineer@solarclear.local` | `Engineer@123` |

**Tables:** `users`, `substations`, `feeders`, `dtrs`, `consumers`, `readings`, `weather`, `applications`, `alerts`, `agent_runs`.

```
substations 1â”€* feeders 1â”€* dtrs 1â”€* consumers
                             dtrs 1â”€* readings
substations 1â”€* weather       dtrs 1â”€* applications *â”€1 consumers
                             dtrs 1â”€* alerts           users 1â”€* applications / agent_runs
```

Every table has an `INTEGER PRIMARY KEY`. Foreign keys use `ON DELETE CASCADE` for child data and `SET NULL` for audit references. `CHECK` constraints enforce enums and positive ratings. `UNIQUE` constraints cover asset codes, accounts, `(dtr_id, ts)` and `(substation_id, ts, kind)`. The important queries are in [db/queries.sql](db/queries.sql).

## How to run

```bash
python -m uvicorn app.main:app --reload --port 8000
```

* App: http://localhost:8000. Log in with a demo account.
* Interactive API docs (Swagger): http://localhost:8000/docs
* Tests: `python -m pytest -v`

## API setup

* **Internal REST API.** Every endpoint is under `/api`. Every route except register, login and health needs `Authorization: Bearer <token>`. The full reference with request and response examples is in [docs/API.md](docs/API.md), and the live version is at `/docs`.
* **D360 AI engine.** Put `D360_AI_API_KEY` and `D360_AI_ENDPOINT` in `.env`. The engine takes the standard chat-completions JSON (`messages`, `tools`, `max_completion_tokens`) and returns `choices[].message.tool_calls` and `usage`.
* **Open-Meteo.** Needs no setup and no key. If the call fails, the forecast falls back to the clear-sky model automatically.
* **Webhook (optional).** Set `NOTIFY_WEBHOOK_URL` to an incoming-webhook URL. It receives `{"text": "..."}` with critical alerts after each scan.

## Usage

1. **Log in** as the engineer. The dashboard ranks DTRs by how much of their hosting capacity they use.
2. Click **Run Grid-Watch agent**. Tick *AI shift brief* if you want a summary from the LLM. The agent forecasts every DTR, raises alerts and evaluates all pending applications.
3. Open a DTR, for example **DTR-S1-02**. You see why it is saturated: the voltage limit binds, and the forecast shows hours above 1.06 pu. Use **Check clearance** to test a new request.
4. On **Applications**, submit a request. It is evaluated straight away. Approve it with the recommended kW, and the DTR's installed PV and headroom update at once.
5. Ask the **Planning Copilot** questions in plain English. Each answer shows which tools it called and how many tokens it used.
6. Sign in as the **admin** and go to **Network assets** to add a DTR or upgrade one's kVA. This is the remedy for a saturated DTR.

## Languages: English and Telugu

The whole application works in **English** and **Telugu (à°¤à±†à°²à±à°—à±)**. Switch with the `English | à°¤à±†à°²à±à°—à±` control on the login card or in the sidebar. The choice is remembered for next time.

| Part | How it is translated |
|---|---|
| UI text (menus, tables, charts, forms, prompts, errors) | `static/locales/en.json` and `static/locales/te.json`. The page applies them at runtime. |
| Text the server generates (clearance reasons, alerts, scan summary) | Templates in `app/i18n.py`. Reasons and alerts are stored in both languages (`decision_reason_te`, `message_te`), so switching language is instant. |
| D360 AI Copilot and shift brief | The client sends `X-Lang: te`. The agent then replies in Telugu and keeps DTR codes, numbers and units as they are. Tool results are sent to the model in English to save tokens. |
| Offline copilot | Understands Telugu keywords, for example à°¸à°‚à°¤à±ƒà°ªà±à°¤, à°…à°‚à°šà°¨à°¾, à°µà±‹à°²à±à°Ÿà±‡à°œà±, à°ªà±à°°à°®à°¾à°¦à°‚, à°¦à°°à°–à°¾à°¸à±à°¤à± and à°•à±à°¸à±à°®à±, and answers in Telugu. |
| Font | Noto Sans Telugu from Google Fonts, with a taller line height for Telugu script. |

To add another language, add a file such as `static/locales/hi.json`, add a `hi` entry to each message in `app/i18n.py`, and add a button to the language switch.

## How the analytics work

For each DTR, the app learns a model from its own last 14 days of meter and weather data:

| Parameter | How it is derived |
|---|---|
| Performance ratio (PR) | Median of metered solar Ã· ideal PV output, on hours above 300 W/mÂ² |
| Peak generation per kW (g) | 98th percentile of normalised output: the planning case of a bright noon |
| Minimum midday load (L_min) | 10th percentile of load between 10:00 and 15:00: the worst case for export |
| Voltage model `V = a + bÂ·export` | Least-squares fit on hourly voltage against net export (RÂ² is shown) |

**Hosting capacity** is how much more PV the DTR can take. It is the minimum of three limits:

* reverse flow: `(REVERSE_FLOW_LIMIT_PCTÂ·kVA + L_min)/g âˆ’ existing PV`
* voltage: `((VOLTAGE_UPPER_PU âˆ’ a)/b + L_min)/g âˆ’ existing PV`
* policy cap: `POLICY_CAP_PCTÂ·kVA âˆ’ existing PV`

Feeder capacity is the smaller of the sum of its DTRs' capacities and the feeder's own reverse-flow limit.

**Status.** A DTR is *saturated* when utilisation is at least 90% or headroom is below 3% of kVA. It is on *watch* when utilisation is at least 70%, when queued applications exceed headroom, or when it is projected to saturate within 12 months at its last-12-month adoption rate.

**Forecast.** For each hour, solar = PV kW Ã— GHI/1000 Ã— PR Ã— temperature derate. Load is the mean for that hour of day over the last 7 days. Net export = solar âˆ’ load, and voltage comes from the fitted model. An hour is flagged when voltage or reverse flow exceeds its limit.

**Clearance** works first come, first served. Headroom is hosting capacity minus the kW already queued ahead of the application. KUSUM requests are also checked against the feeder's headroom. If the request fits in the headroom, the result is *clear*. If at least 1 kW of headroom is left, it is *partial*, with the largest clearable size or export limiting suggested. Otherwise it is *reject*, with DTR augmentation suggested.

## How the agent saves tokens

* **Decisions are deterministic.** Forecasts, hosting capacity, alerts and clearances are all computed in Python. The LLM never produces a number; it only chooses tools and writes the answer.
* **Tool results are compact.** They are minified JSON capped at 2,500 characters, internal model details are stripped, lists are capped (top 10 or 12), and a forecast returns peak and risk hours rather than all 48 points.
* **The conversation context is bounded.** The system prompt is short (about 100 words), only the last 6 chat turns are sent with each clipped to 600 characters, and there are at most 4 tool rounds.
* **Each call is capped.** `reasoning_effort=low` and `max_completion_tokens` are set on every call.
* **A Grid-Watch scan costs 0 tokens**, plus one optional call of about 750 tokens for the brief.
* **A typical copilot question uses about 1.5 to 1.7k tokens.** Every run's usage is recorded in the **Agent log**.

## Design notes and assumptions

* The DTR hosting model is linear and steady-state, learned from metered data. It is a screening tool, not a replacement for a full power-flow study on borderline cases.
* The sample data is synthetic. Connecting real AMI or DT-meter data only means loading the `readings` table, which uses the same columns.
* The planning limits (voltage, reverse flow, policy cap) differ by state regulation, so they are configuration settings rather than hard-coded values.
* The agent is read-only by design: it recommends, and an engineer decides (human in the loop).

## Security

* `.env` holds the keys and is gitignored. `.env.example` contains no secrets.
* Passwords are salted PBKDF2 hashes. Tokens are signed and expire.
* All SQL is parameterised. Dynamic `UPDATE` column names come only from validated schema fields.
* The UI escapes all user and agent text before rendering it.
* Change `SECRET_KEY` and the demo passwords before any real deployment.
