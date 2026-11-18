# Offline LAN Ollama AI (`qwen3:1.7b` / `qwen3:4b-q4_K_M`)

WellCostIQ supports an optional, fully offline local-area-network (LAN) AI model
served by **Ollama** (compact models such as `qwen3:1.7b` as well as
`qwen3:4b-q4_K_M`) running on another PC on the same network (or locally). No
data is ever sent to any public cloud API, and everything continues to work
deterministically when `OLLAMA_ENABLED=false` (the default) or when the remote
AI host is temporarily offline.

## What it does

1. **Workspace Database, D&C Engineering & Workflow Guide (`/assistant` and `/operations/guide`)**
   - Answers natural-language questions over the caller's live, permitted
     workspace records and shipped/custom application workflows.
   - Computes exact `Decimal` figures and side-by-side multi-well comparisons
     before handing the context to the model — e.g.
     `I need "Well X" total cost and compare with "Well Y" cost` returns exact
     recorded cost, LIH register cost, total cost including LIH, effective AFE
     budget (including SOW adjustments), remaining balance, Actual / AFE %,
     cost-group split, NPT/UPA exposure, schedule days, and exact head-to-head
     differences.
   - Reads across wells, rigs, blocks, AFEs & SOW adjustments, Daily Cost
     sheets, Mud Cost reconciliation, LIH Cost Register, Fuel Cost Register,
     NDT Inspections, Invoice Processing / IDVS, Vendors & PO/SO orders,
     Services, Priced Catalogue items (Tangibles, Drill Bits, Mud Chemicals,
     Cement Additives, Fuel), Entry Checks, and Cost Intelligence findings.
   - Falls back automatically to verified local workspace data while raising a
     clear communication error alert if the remote AI host fails.

2. **Opt-in AI Review in Cost Intelligence (`/reports/cost-intelligence`)**
   - Off by default — standard statistical Cost Intelligence runs without ever
     touching the AI host.
   - Switch on **Engage AI model** whenever you want an on-demand review across
     either the filtered **Portfolio** or a **Selected well**, with four focus
     modes (*Comprehensive cost review*, *Anomalies & cost drift*, *Suspected
     data-entry mistakes*, *AFE budget, forecast & NPT*) plus an optional custom
     audit question.
   - Combines deterministic anomaly/trend/forecast metrics with open Daily Cost
     Sheet Entry Check mistake signals and unbudgeted/reconciliation ledger data
     into an executive summary, severity-ranked findings, direct links to the
     offending sheets/well analyses, and prioritized recommendations.
   - When an AI review is active, *Export report* offers an optional **AI cost
     analytic review** section for PDF and an **AI review** worksheet for Excel.

3. **Well Operations D&C Intelligence, AI Prefill, Narratives & Operational Review**
   - **AI Extraction & Gap Prefill** (`POST /operations/reports/extract` with `use_ai=true` and `POST /operations/reports/{id}/ai-prefill`): deterministic parsers extract all MDs, TVDs, bit depth, casing, mud properties, BHA, surveys, codes and WAT (`UTC+1:00`) blocks first; Offline AI optionally fills remaining missing header fields and refines unclassified activity blocks as reviewer suggestions without overwriting measured numbers.
   - **AI D&C Narrative Generator** (`POST /operations/reports/{id}/narratives`): drafts engineering-grade 24-hour operation summary, 24-hour forecast, HSE summary, and brief grounded strictly in saved report data, with instant deterministic fallback.
   - **AI Operational Analytics Review** (`POST /operations/ai-review` on `/operations/summary` and `/operations/analytics`): on-demand drilling & completion review across Comprehensive, NPT & Unplanned Delay, ROP & Drilling Optimization, and Wellbore/Mud/HSE focus areas.
   - **Daily brief, timeline study & Well Operations Ask & Guide** (`/operations/guide`): compact `qwen3:1.7b`-tuned prompts with automatic Qwen3 `/no_think` handling and strict RBAC context boundaries.

---

## 1. Set up the remote Ollama PC on your LAN

Suppose WellCostIQ runs on `192.168.1.10` and the dedicated AI PC on the same
LAN has static/reserved IP `192.168.1.50`.

### Pull the model

```sh
ollama pull qwen3:4b-q4_K_M
ollama list
```

> **Air-gapped sites:** pull `qwen3:4b-q4_K_M` once on a staging machine, copy
> the Ollama models directory (`~/.ollama/models` on Linux/macOS or
> `%USERPROFILE%\.ollama\models` on Windows) to the offline LAN PC, and restart
> the Ollama service.

### Bind Ollama to the LAN interface

By default Ollama listens only on `127.0.0.1:11434`. Set `OLLAMA_HOST` on the
**AI PC** so the WellCostIQ server can reach it over the LAN:

- **Linux (`systemd`):**
  ```sh
  sudo systemctl edit ollama.service
  ```
  Add:
  ```ini
  [Service]
  Environment="OLLAMA_HOST=0.0.0.0:11434"
  Environment="OLLAMA_KEEP_ALIVE=15m"
  ```
  Then reload and restrict port `11434` to the WellCostIQ server or LAN subnet:
  ```sh
  sudo systemctl daemon-reload && sudo systemctl restart ollama
  sudo ufw allow from 192.168.1.0/24 to any port 11434 proto tcp
  ```

- **Windows (PowerShell as Administrator):**
  ```powershell
  [System.Environment]::SetEnvironmentVariable("OLLAMA_HOST", "0.0.0.0:11434", "User")
  New-NetFirewallRule -DisplayName "Ollama LAN (WellCostIQ)" `
    -Direction Inbound -Protocol TCP -LocalPort 11434 `
    -RemoteAddress LocalSubnet -Action Allow
  ```
  Quit Ollama from the system tray and start it again.

- **macOS:**
  ```sh
  launchctl setenv OLLAMA_HOST "0.0.0.0:11434"
  ```
  Quit and relaunch Ollama.app.

### Verify LAN connectivity from the WellCostIQ host

```sh
curl -fsS http://192.168.1.50:11434/api/tags
```

You should see `"name":"qwen3:4b-q4_K_M"` in the returned JSON.

---

## 2. Configure `.env` on the WellCostIQ host

Add or edit these variables in `.env` (for Docker Compose) or `backend/.env`
(for local `uvicorn` runs):

```dotenv
OLLAMA_ENABLED=true
OLLAMA_BASE_URL=http://192.168.1.50:11434
OLLAMA_API_PATH=/api/chat
OLLAMA_TAGS_PATH=/api/tags
OLLAMA_MODEL=qwen3:4b-q4_K_M
OLLAMA_API_KEY=
OLLAMA_CONNECT_TIMEOUT_SECONDS=5
OLLAMA_TIMEOUT_SECONDS=90
OLLAMA_TEMPERATURE=0.1
OLLAMA_NUM_CTX=8192
OLLAMA_MAX_TOKENS=1200
OLLAMA_THINK=false
OLLAMA_KEEP_ALIVE=15m
OLLAMA_CA_CERT=
```

### Complete `.env` reference

| Variable | Default | Range / Format | Purpose |
| --- | --- | --- | --- |
| `OLLAMA_ENABLED` | `false` | `true` / `false` | Master switch for LAN Ollama connectivity |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | `http://` or `https://` host[:port][/prefix] | IP, `.local` mDNS name, or hostname of the remote Ollama PC on the LAN. Embedded credentials (`user:pass@`) are rejected; if `/api/chat` or `/v1/chat/completions` is pasted on the end, it is normalized automatically |
| `OLLAMA_API_PATH` | `/api/chat` | `/api/chat`, `/api/generate`, or `/v1/chat/completions` | Chat/generation route on the remote Ollama server |
| `OLLAMA_TAGS_PATH` | `/api/tags` | Leading `/` path | Health and installed-model discovery route used by **Check connection** |
| `OLLAMA_MODEL` | `qwen3:4b-q4_K_M` | Ollama model tag | Target offline model (`qwen3: 4b-q4_K_M` accidental whitespace around `:` is normalized automatically) |
| `OLLAMA_API_KEY` | *(empty)* | Secret string | Optional `Authorization: Bearer <token>` if an authenticating reverse proxy (Nginx/Caddy/Traefik) sits in front of Ollama. Masked in startup summaries and `repr()` |
| `OLLAMA_CONNECT_TIMEOUT_SECONDS` | `5` | `1`–`60` s (`<= OLLAMA_TIMEOUT_SECONDS`) | TCP handshake timeout so an offline/powered-down LAN PC fails fast and alerts immediately |
| `OLLAMA_TIMEOUT_SECONDS` | `90` | `5`–`300` s | Total response read timeout (raise to `180`–`240` for CPU-only LAN machines) |
| `OLLAMA_TEMPERATURE` | `0.1` | `0.0`–`1.0` | Low temperature keeps cost numbers and comparisons deterministic |
| `OLLAMA_NUM_CTX` | `8192` | `1024`–`65536` | Context window passed to Ollama `options.num_ctx` |
| `OLLAMA_MAX_TOKENS` | `1200` | `64`–`8192` | Maximum completion tokens (`num_predict` / `max_tokens`) |
| `OLLAMA_THINK` | `false` | `true` / `false` | Controls Qwen3 chain-of-thought; `false` gives fast direct answers on a 4B quantized model (any `<think>…</think>` block is stripped either way) |
| `OLLAMA_KEEP_ALIVE` | `15m` | e.g. `15m`, `1h`, `0`, `-1` | How long Ollama keeps `qwen3:4b-q4_K_M` warm in RAM/VRAM between questions |
| `OLLAMA_CA_CERT` | *(empty)* | Filesystem path | Optional PEM CA certificate file when `OLLAMA_BASE_URL` uses `https://` with an internal corporate/LAN CA |

---

## 3. Starting WellCostIQ with LAN Ollama access

### Docker Compose (recommended)

The base `docker-compose.yml` keeps `backend_net` marked `internal: true` so the
API container has zero outbound network access when AI is disabled. When
`OLLAMA_ENABLED=true`, include the committed `docker-compose.ollama.yml`
override so the `api` container can reach the LAN Ollama PC while `db` remains
completely isolated:

```sh
docker compose -f docker-compose.yml -f docker-compose.ollama.yml up -d --build
# or shorthand:
make up-ai
```

> If Ollama runs on the Docker host machine itself, set
> `OLLAMA_BASE_URL=http://host.docker.internal:11434` (`host-gateway` is already
> mapped in `docker-compose.ollama.yml`).

### Local without Docker

Restart `uvicorn` after editing `backend/.env`:

```sh
cd backend && ../.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

## 4. Communication error alerts & troubleshooting

Whenever WellCostIQ cannot communicate with the configured LAN Ollama model, the
user receives **two clear alerts**:

1. An inline accessible alert (`role="alert"`) inside the Guide or Cost
   Intelligence AI panel displaying the failure category, model, configured LAN
   host, actionable fix, and **Retry AI request** / **Check connection** buttons.
2. A persistent top-right notification banner (`api-error`) so transient LAN
   drops are never missed.

| `error_code` | Meaning | Fix |
| --- | --- | --- |
| `disabled` | `OLLAMA_ENABLED=false` | Set `OLLAMA_ENABLED=true` in `.env` and restart the API (use `make up-ai` on Docker Compose) |
| `connection_refused` | LAN host reached, port closed | Start Ollama on the AI PC and set `OLLAMA_HOST=0.0.0.0:11434` (not `127.0.0.1`) |
| `unreachable` | No route / firewall drop | Check LAN IP in `OLLAMA_BASE_URL`, host firewall rule on TCP `11434`, and `docker-compose.ollama.yml` |
| `dns_error` | Hostname / `.local` did not resolve | Use the AI PC's static LAN IP (e.g. `http://192.168.1.50:11434`) or fix LAN DNS |
| `timeout` | Host did not answer within timeout | Confirm PC is awake; if running on CPU, increase `OLLAMA_TIMEOUT_SECONDS=180` and keep `OLLAMA_THINK=false` |
| `tls_error` | HTTPS certificate rejected | Point `OLLAMA_CA_CERT` at the internal CA PEM file (mounted read-only into the API container) |
| `auth_error` | Proxy returned `401`/`403` | Set the matching Bearer token in `OLLAMA_API_KEY` |
| `model_missing` | Ollama running, model absent | Run `ollama pull qwen3:4b-q4_K_M` on the AI PC (the alert lists installed models so tag mismatches are obvious) |
| `bad_endpoint` | `404`/`405` or HTTP redirect | Set `OLLAMA_API_PATH=/api/chat` (or `/v1/chat/completions`) and remove proxy redirects |
| `server_error` | Ollama `5xx` (often low RAM/VRAM) | Free memory on the AI PC or lower `OLLAMA_NUM_CTX` (e.g. `4096`) |
| `invalid_response` | Non-JSON or empty reply | Verify `OLLAMA_BASE_URL` points to Ollama (not a web UI) and keep `OLLAMA_THINK=false` |

---

## 5. Security, tenant isolation & verification

- **Zero raw SQL from the model:** the model never generates or executes queries.
  The backend reads strictly `organization_id`-scoped records via existing
  services under the caller's exact RBAC capabilities, computes all totals and
  variances with Python `Decimal`, and refuses restricted capabilities before
  calling Ollama.
- **No SSRF surface:** `OLLAMA_BASE_URL` comes exclusively from server `.env`
  configuration — never from request parameters or database rows — and HTTP
  redirects are rejected.
- **No credentials exposed:** `OLLAMA_API_KEY` is never logged, serialized, or
  returned by `/ai-status`.
- **Immutable audit trail:** every AI Guide question (`entity_type="assistant"`,
  `action="ai-query"`) and Cost Intelligence AI review
  (`entity_type="cost_intelligence"`, `action="ai-review"`) — including failed
  communication attempts — writes an `AuditLog` entry.
- **No external runtime dependency:** `backend/app/services/ollama.py` uses
  Python's standard `http.client` and `ssl` modules only.
- **Automated checks:**
  - `cd backend && ../.venv/bin/python -m pytest -v tests/test_ollama_ai.py`
  - `make ollama-ai-check`
