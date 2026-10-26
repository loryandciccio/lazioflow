# LazioFlow

### Conversational healthcare navigation: structured AI, deterministic safeguards and transparent ranking

Developed by **Lorenzo Cozzolino**, in collaboration with **Luca Peperoni** and **Emilio Falco**.

LazioFlow is a Python and Telegram prototype for interpreting healthcare-service requests in Italian and explaining how compatible facilities are ranked. The original academic project integrated heterogeneous sources for the Lazio region, a FastAPI backend, an optional language model, deterministic safety rules and a SQLite observation collector.

**This public edition ships with a small, entirely synthetic catalogue of 17 fictional facilities.** It demonstrates the software without redistributing the original source datasets, cached webpages, operational records or development history. The API and bot identify the catalogue as a demo; fictional facilities have no navigation links. This edition must not be used to find actual healthcare services.

> Academic and software demonstration only. LazioFlow does not diagnose conditions, assign triage codes, establish medical safety or predict when a person will receive care. It is not an official healthcare service and has not been clinically validated.

## What the project demonstrates

- **Structured intent parsing:** optional Anthropic or Groq integration with a closed Pydantic output schema and a deterministic fallback.
- **Independent safety decisions:** 38 configured rules inspect the original request. A hard red flag handled by `/understand` takes precedence over ordinary routing and does not wait for an LLM response.
- **User confirmation:** the Telegram flow asks users to confirm an interpretation or select a facility type before searching by location.
- **Hierarchical ranking:** facility type, compatibility, known opening information and the selected preference determine the order, with explicit reasons and warnings.
- **Data-quality handling:** source freshness, missing information and historical trends are represented separately from forecasts.
- **Modular integration:** FastAPI, Telegram handlers, source adapters, SQLite polling and explanation generation are separate components.
- **Automated verification:** offline tests cover parsing, safety, ranking, API access, source adapters, session handling and the public demo's network protections.

## Architecture

```text
Telegram bot                         FastAPI backend
  commands and free text ----------> /understand
  confirmation and session state       deterministic safety + parser/fallback
  explicit service and location ---> /recommend
                                        compatibility + hierarchical ranking
                                        reasons, warnings and freshness
                                             |
                                  synthetic normalized catalogue

Optional integrations retained in the code:
  LLM adapters | external source adapters | SQLite observation poller
```

The language model interprets text; it does not select invented real-world facilities or compute the ranking. Explanations use supplied recommendation facts, with a deterministic template fallback.

### Ranking policy

Travel estimates and observed emergency-department waiting times are never summed into a predicted time to care. Stale waiting observations do not affect waiting-based ordering. Trends describe past observations, not future demand.

| Preference | Ordering after compatibility checks |
|---|---|
| `balanced` | Candidates with usable recent observations first, then estimated travel time; observed waiting time breaks travel-time ties. |
| `nearest` | Estimated travel time without using waiting observations for ordering. |
| `less_crowded` | Usable observed waiting time; estimated travel time is the fallback. This is not a forecast of crowding. |

Pharmacies and community-care facilities use travel-based ordering. Travel estimates follow declared distance and average-speed assumptions, not real-time traffic. See [config/ranking.yaml](config/ranking.yaml). The public synthetic catalogue includes no real waiting observations or verified opening hours.

## Technology

Python 3.12+, FastAPI, Pydantic, HTTPX, SQLite, python-telegram-bot, pytest and optional Anthropic/Groq adapters.

## Run the demo

Use Python **3.12 or newer**. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev,data]"
cp .env.example .env
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

The provided configuration disables AI and external source collection. The synthetic catalogue also keeps the backend collectors disabled if `LAZIOFLOW_LIVE=1` is set accidentally. Dependency installation needs Internet access; using the local API demo does not need provider credentials.

In another terminal:

```bash
curl -sS http://127.0.0.1:8000/understand \
  -H 'Content-Type: application/json' \
  -d '{"text":"cerco una farmacia"}'

curl -sS http://127.0.0.1:8000/recommend \
  -H 'Content-Type: application/json' \
  -d '{"category":"FARMACIA","location":{"lat":41.9028,"lng":12.4964},"preference":"nearest"}'
```

Explore the schema at `http://127.0.0.1:8000/docs`. Recommendation responses include `synthetic: true` and an explicit demo disclaimer. `/health` normally reports `degraded` because the synthetic demo has no real poller history; HTTP 200 alone does not mean that live data are available.

These examples assume loopback-only development without a configured API key. If you configure a key, supply the matching `X-API-Key` header.

### Optional Telegram interface

Create your own Telegram bot and put its token privately in the root `.env`, then start a separate process:

```bash
source .venv/bin/activate
python -m bot.bot
```

Keep the API running in the first terminal. Telegram itself is an external service: enabling this interface sends the user's messages through Telegram and the configured backend. Use synthetic requests for demonstrations. Do not run two bot polling processes with the same token.

| Command | Purpose |
|---|---|
| `/start`, `/help` | Start a session and read instructions. |
| `/ps`, `/cdc`, `/farmacia` | Select emergency departments, community healthcare or pharmacies. |
| `/rete`, `/copertura` | Inspect observations and catalogue/source coverage. In this edition these concern the synthetic demo. |
| `/info`, `/privacy` | Read source limitations and technical data handling. |
| `/stop` | Clear the bot's local in-memory session. |

### Optional language models

Rules are the default: no AI key is required. To enable an LLM deliberately, set `LAZIOFLOW_AI=1`, select `LLM_PROVIDER=anthropic` or `groq`, and configure both the matching private key and a model identifier supported by your account and the adapter. `auto` prefers a configured Anthropic client and otherwise tries Groq.

Enabling AI sends the request text to the selected provider and may incur charges. Do not use private medical information in demonstrations. Invalid outputs, refusals and failed requests fall back to rules. Provider spending limits must be set separately; request quotas are not a monetary cap.

## Configuration

Copy `.env.example` to a private root `.env`; never commit actual values.

| Variable | Purpose |
|---|---|
| `TELEGRAM_TOKEN` | Token for your own Telegram bot; empty by default. |
| `BACKEND_URL` | API address used by the bot; defaults to loopback. |
| `LAZIOFLOW_AI` | LLM opt-in; defaults to `0`. |
| `LLM_PROVIDER` | `auto`, `anthropic` or `groq`. |
| `ANTHROPIC_API_KEY`, `CLAUDE_MODEL` | Private Anthropic credential and compatible model identifier. |
| `GROQ_API_KEY`, `GROQ_MODEL` | Private Groq credential and compatible model identifier. |
| `LAZIOFLOW_LIVE` | Live-source opt-in for an authorized real catalogue; synthetic data keep collection disabled. |
| `LAZIOFLOW_DB` | SQLite observation path shared by API and poller. |
| `LAZIOFLOW_ENV` | `development` or `production`. |
| `LAZIOFLOW_API_KEY` | Shared backend key, also configured in the bot. |
| `API_REQUESTS_PER_MINUTE` | General quota per backend process. |
| `AI_REQUESTS_PER_MINUTE` | Shared quota for the three AI-related endpoints, per process. |
| `LOCATION_TTL_S` | Session lifetime; example default is 2,700 seconds. |

## API

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/understand` | Combined parsing and deterministic safety decision. |
| `POST` | `/parse` | Structured intent extraction only. |
| `POST` | `/safety/check` | Deterministic check of the supplied text. |
| `POST` | `/recommend` | Rank catalogue candidates for a category, location and preference. |
| `POST` | `/explain` | Explain supplied ranking facts, with a template fallback. |
| `GET` | `/categories` | Supported request categories. |
| `GET` | `/facilities/{facility_id}` | Catalogue record. |
| `GET` | `/ps/live` | Available observations; no real live observations in the synthetic demo. |
| `GET` | `/sources`, `/coverage`, `/health` | Source information, coverage and runtime status. |

`/parse` and `/recommend` are individual components, not substitutes for the combined bot safety and confirmation flow.

## Tests

```bash
python -m pytest -q
```

The ordinary suite disables AI and live fetching, uses a temporary database and does not require real credentials. Source-adapter and LLM failure cases use mocks. Tests also check that synthetic recommendations are identified as fictional, do not expose navigation buttons and do not open outbound connections, and that the poller refuses the synthetic catalogue before fetching anything.

A credential-dependent optional test may be skipped. Passing software tests does not establish clinical validity or certify a public deployment. The tests do not contact real Telegram users or prove that external providers are available.

## Data and third-party rights

Only generated fictional facility records and the project's category definitions are included. Real source exports, cached HTML, historical observations, operational logs and old academic validation reports are not distributed in this public edition.

The source adapters and acquisition scripts remain available for inspection. They are **not run automatically by the demo**. The original full data build also relied on curated joins and reference inputs that are not bundled here: a complete real-world catalogue cannot be regenerated from this repository with a single command.

To work with real data, first obtain the required permissions and inputs, then build and validate a catalogue matching the schema and its metadata. Do not relabel the fictional demo as real data. Real-source collection and public healthcare deployment require separate validation.

See [data/README.md](data/README.md), [source feasibility notes](docs/FATTIBILITA.md) and the [public-release data-rights boundary](docs/DATA_RIGHTS.md). Links to external services are references, not permission to redistribute their contents. Libraries and any separately obtained data retain their respective terms.

## Privacy and security

- No actual API keys, user conversations, medical records or private runtime databases are included.
- AI and backend source collection are off by default. Explicit Telegram, AI or acquisition-script use introduces external data flows as documented above.
- The original free text is not retained in the bot's session state. Location is used by the backend search, not included in the LLM intent-parsing payload.
- Session category, location and results remain in memory until expiry. `/stop` clears the local session, not Telegram messages or provider-side records.
- Bind the development API to `127.0.0.1`. Before remote access, configure `LAZIOFLOW_ENV=production`, a strong private API key, HTTPS/access controls and provider budgets. Production without a configured key returns 503.
- Quotas are in memory and per process. Multiple workers need an external shared control; this is not a high-availability production service.

See [operational notes](docs/OPERATIVITA.md). Publishing this code does not start an API server. A real deployment also needs an operator, a complete privacy notice and qualified review of safety messages and service information.

## Limitations

The bundled facilities are fictional and unsuitable for real navigation. The original source integrations had incomplete coverage, changing formats and missing opening information. Observations do not predict an individual's wait. Deterministic rules have limited language coverage, are intentionally conservative and do not fully resolve negation; absence of a detected flag does not establish medical safety.

Clinical triage, forecasts, dashboards and weather-based medical inference are outside the implemented scope. Weather collection code is retained as part of the original poller, not used to infer urgency. Rule source references are documented in [safety/SOURCES.md](safety/SOURCES.md); they do not constitute clinical certification.

## Repository structure

```text
ai/                  Structured parsing, provider adapters and explanations
backend/app/         API, compatibility, ranking and source adapters
bot/                 Telegram handlers, rendering and session state
config/              Explicit ranking parameters
data/normalized/     Synthetic catalogue and category definitions
data/scripts/        Explicit acquisition/build utilities; not automatic
docs/                Scope, source limitations and operational notes
poller/              Collection/export code; refuses the synthetic catalogue
safety/              Deterministic rules and source references
tests/               API, integration and public-demo protection tests
```

Additional tests are in `ai/tests/` and `safety/tests/`. Most bot messages and code comments remain in Italian; the public documentation is in English.

## Attribution and licensing

Third-party libraries and source references are acknowledged through the dependency metadata and documentation. No general open-source licence is currently granted for the project code; public visibility alone does not imply an MIT or Apache licence. Do not apply a project-wide licence to separately obtained third-party data or assets.
