# TraceGrid – API Monitoring & Analytics Platform

TraceGrid is a web-based API monitoring platform that allows users to register API endpoints, monitor their availability, track response times, and view monitoring history and analytics.

## Features

- User registration with email verification, password recovery, and JWT authentication
- Add, view, update, and delete API endpoints
- Manual API health checks
- Durable scheduled health checks with a 30-second target interval
- UP/DOWN status detection
- HTTP status code and response-time tracking
- Monitoring history stored in PostgreSQL
- Endpoint analytics and uptime percentage
- Dashboard with monitoring statistics
- Live monitoring updates over authenticated WebSockets
- Automatic availability incidents, lifecycle tracking, live in-app alerts, and opt-in incident email
- Time-windowed latency, availability, endpoint comparison, and incident analytics
- Automated backend tests using Pytest

### Availability reporting

Uptime is the percentage of availability samples returning HTTP 2xx. Endpoints without samples show **No data**. HTTP redirects are displayed with their status code, left unfollowed, and counted as unsuccessful availability samples.

Unsuccessful HTTP responses, missing DNS names, refused or reset connections, TLS failures, and probe timeouts after DNS validation count as target failures from the monitor's vantage point. Temporary DNS failures, DNS lookup timeouts, and local probe errors appear in history as monitoring errors and are excluded from uptime, failed checks, and average response time. The latest scheduled configuration block is displayed separately and clears after a successful probe or a validated endpoint edit.

## Technologies Used

**Backend:** Python, FastAPI, SQLAlchemy

**Frontend:** React, Vite, JavaScript, CSS

**Database:** PostgreSQL

**Authentication:** JWT, Argon2 password hashing

**Testing:** Pytest, FastAPI TestClient

**Monitoring:** HTTPX, APScheduler

## Project Structure

```text
TraceGrid/
├── app/
│   ├── models/
│   ├── routes/
│   ├── schemas/
│   ├── services/
│   ├── config.py
│   ├── database.py
│   ├── security.py
│   └── main.py
├── frontend/
│   └── src/
│       └── pages/
├── tests/
│   ├── conftest.py
│   ├── test_auth.py
│   ├── test_endpoints.py
│   └── test_monitoring.py
├── requirements.txt
└── README.md
```

## Setup and Installation

### 1. Clone the repository

```bash
git clone https://github.com/VishwaTejaPathipaka/TraceGrid.git
cd TraceGrid
```

### 2. Create and activate a virtual environment

```bash
python -m venv venv
venv\Scripts\activate
```

### 3. Install backend dependencies

```bash
python -m pip install --upgrade "pip>=26.3"
python -m pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file in the project root:

```env
DATABASE_URL=postgresql+psycopg2://username:password@localhost:5432/tracegrid
SECRET_KEY=your-secret-key
ALGORITHM=HS256
```

Create the PostgreSQL database named `tracegrid` before starting the application.

### 5. Upgrade the database and start the backend

Set `DATABASE_URL` in the migration process environment and run `alembic upgrade head` from the repository root before starting PostgreSQL-backed workers. The migration supports a fresh database or the existing unversioned TraceGrid schema. It preserves endpoints and history and spreads existing first due times across the next 30 seconds. Stop old scheduler workers during the rollout so the former sweep job cannot run alongside the new dispatcher.

### Account email and password recovery

An instance on revision `20261123_01` needs the additive `20261123_02` migration before starting the updated backend. Apply it manually with `alembic upgrade 20261123_02` using the intended database configuration. Existing users keep their passwords and sign-in access. If legacy accounts share a case-insensitive email, self-service recovery is unavailable for those accounts until an administrator resolves the ambiguity.

TraceGrid requires new accounts to confirm their mailbox and enter their account password before sign-in. Verification links expire after 24 hours. Reset links expire after 30 minutes. Both links are single-use, and a replacement invalidates the previous link for that purpose. A password reset ends existing sessions, including dashboard WebSockets. New passwords are 12–128 characters and are hashed with Argon2.

- **Local development.** The default `EMAIL_DELIVERY=outbox` writes `.eml` messages to the ignored `.tracegrid-mail/` directory. Open the latest message in an email viewer and follow its link. `EMAIL_OUTBOX_DIR` can point to a different private directory. The default `ACCOUNT_LINK_BASE_URL` is `http://localhost:5173`. Treat outbox messages as sensitive and remove them after testing.
- **Production SMTP.** Select `EMAIL_DELIVERY=smtp` and configure `EMAIL_FROM` and `SMTP_HOST`. Set `ACCOUNT_LINK_BASE_URL` to the public HTTPS frontend URL. `SMTP_PORT` defaults to 587 and `SMTP_TLS` to `starttls`. Use `SMTP_TLS=implicit` with port 465 if required by your provider. Set both `SMTP_USERNAME` and `SMTP_PASSWORD` through your secret store if the relay requires authentication. Configure the frontend host to serve the React app for the account-link routes.
- **Delivery behavior.** Link requests return a generic acknowledgement. The backend attempts delivery after the response, logs delivery failures without message contents, and allows a replacement after a one-minute per-account cooldown. Rate-limit public auth routes at the ingress in production.

### Incidents

Apply the additive `20261123_03` migration before starting the incident-enabled backend. Tracking starts with new checks after migration. Incident detection does not backfill prior probe history.

Three unsuccessful availability results for an owned endpoint open an incident. Both scheduled and manual probes count. Redirects count as unsuccessful, while monitoring and configuration errors leave the streak unchanged. A successful probe clears the streak and resolves an active incident. The first failure sets the start time, and the third records the triggering reason and HTTP status. Severity is critical when the trigger has no HTTP status or returns 5xx and warning for other unsuccessful HTTP responses. An endpoint edit or manual resolution clears its streak.

The Incidents page supports acknowledgment, manual resolution, and filters by status, endpoint, and UTC start date. The overview shows active incidents and resolutions from the past seven days. Live alerts are delivered in the app over the existing owner-scoped WebSocket.

#### Incident email notifications

Apply additive migration `20261123_04` before starting the notification-enabled backend. In **Settings**, verified owners can independently opt in to incident-open and automatic-recovery emails. Both preferences default to off. TraceGrid did not previously record proof of mailbox verification separately from sign-in eligibility, so existing accounts must request a new verification link before opting in. Existing sign-in access is preserved. Acknowledgement, manual resolution, and historical incidents do not generate emails.

TraceGrid queues at most one logical email per eligible incident transition in the probe transaction. A PostgreSQL advisory lock elects one delivery worker per database. Jobs commit a lease before delivery and can be recovered after a crash. The worker rechecks the owner's verified address and preference before sending. A message already in flight may still arrive after preferences change.

The worker retries transient failures up to five total attempts with exponential backoff starting at 30 seconds. Permanent delivery errors stop retrying. Jobs expire after 24 hours and terminal records are pruned after 30 days. SMTP is outside the probe transaction. Delivery is effectively **at least once** when retried. If SMTP accepts a message immediately before a worker crashes, a retry may send a duplicate.

Development uses the same local `.eml` outbox as account email. Production uses the existing `EMAIL_DELIVERY=smtp` settings and TLS requirements documented above. Incident links use `ACCOUNT_LINK_BASE_URL`. Messages show the endpoint origin only and do not include its URL path, query, credentials, or fragment.

### Request and resource limits

Apply additive migration `20261123_06` before starting the hardened backend. PostgreSQL atomically enforces the same fixed-window counters across every API worker. Limits return HTTP 429 and a `Retry-After` header in seconds. Expired counters are pruned in bounded batches. Account responses and limits use the same rules for known and unknown identifiers.

| Operation | Default limit |
| --- | --- |
| Login | 90 per source per 5 min, 8 per source and username per 5 min, 40 per username per 15 min, 600 per deployment per min |
| Registration | 20 per source per hour, 180 per deployment per min |
| Password-recovery and verification-link requests combined | 30 per source per 15 min, 5 per source and address per 15 min, 240 per deployment per min |
| Password reset and email verification submissions combined | 30 per source per 5 min, 240 per deployment per min |
| Endpoint create and update | 20 per owner per min and 50 endpoints per owner |
| Manual checks | 12 per owner per min, one in flight per owner and four across the deployment. Endpoint destination validation shares the concurrency budget. |
| Analytics (including Overview aggregate) and history | 60 analytics requests and 60 history requests per owner per min |
| WebSocket admission | 90 handshakes per source per min, 900 per deployment per min, and 30 authenticated admissions per owner per min |

Sources use the actual IPv4 address or IPv6 /64. Configure counts with `SECURITY_RATE_OVERRIDES`, for example `{"manual_check": 16}`. Valid keys and fixed window lengths are in `app/config.py`. Keep the same settings across workers. The per-username login budget slows distributed guessing and can temporarily throttle the targeted account when exhausted.

Request bodies are limited to 16 KiB with a 10-second read deadline. The supported launcher caps WebSocket messages at 8 KiB. Each server worker allows up to 64 sockets, 16 per source, and 6 per owner. Admission rates remain shared across workers. Set ingress limits for the desired deployment-wide socket count. Argon2 work is capped at four operations per worker. Scheduled probes keep separate slots and default to two concurrent probes per owner across PostgreSQL workers. Change these bounds through the `MAX_*`, `MANUAL_PROBE_SLOTS`, `PASSWORD_HASH_SLOTS_PER_WORKER`, or `SCHEDULED_PROBES_PER_OWNER` settings as appropriate.

The monitoring history endpoint still returns an array. It defaults to 100 rows and accepts a `limit` up to 250 and an optional `before_id` from the preceding page. The React history view follows the cursor.

### Monitoring-history retention

Retention is disabled by default. No scheduler, web route, or background worker runs deletion. A database operator can run a read-only estimate through standard PostgreSQL authentication:

```powershell
python -m app.maintain_history --database TraceGrid --user postgres --days 90
```

Deletion requires a separate, explicit invocation with `MONITORING_RETENTION_ENABLED=true`, `--apply`, and `--confirm-database` matching the connected database name. The database role must have DELETE access to `public.monitoring_history`. Use a dedicated maintenance role and take a verified backup before authorizing retention. Keep the enable flag out of the service environment.

The command uses one database advisory lock, freezes the UTC cutoff for that run, skips locked rows, and commits each bounded batch. Defaults are 500 rows and at most 100 batches per invocation. Rows exactly at the cutoff and rows with no recorded time remain. An interruption keeps earlier committed batches, and another authorized invocation resumes scanning eligible rows. Other tables are outside the deletion query. Dry-run output includes only the UTC cutoff and aggregate counts.

Overview and analytics use available monitoring records. Removing older checks can change historical uptime and latency denominators. Missing records are never filled with inferred outcomes. Incident counts and recovery durations remain based on incident records.

For public deployment, terminate TLS at your ingress, serve the built frontend, and keep the API listener private to that ingress. Use `python -m app.serve` for the configured proxy and transport limits. Forwarded headers are ignored by default. Set `TRUSTED_PROXY_NETWORKS` only to the actual proxy addresses, and have proxies replace inbound forwarded headers. Use exact HTTPS `FRONTEND_ORIGINS`, a strong random JWT signing key, and `ENABLE_HSTS=true` only when HTTPS is in place. Set ingress body, header, connection, and request limits and enforce outbound network policy. Application SSRF validation is defense in depth alongside egress firewall restrictions to private networks and metadata services.

### Advanced analytics

**Analytics** compares owned endpoints and summarizes incident activity. Select an endpoint for a time-based latency trend, availability timeline, and latency distribution. You can also open these views from an endpoint's **Analytics** tab. All views share 1-hour, 6-hour, 24-hour, and 7-day windows. Chart timestamps display in local time.

Redirects count as unsuccessful availability checks. Internal monitoring errors appear separately and do not contribute to uptime or latency statistics. Configuration blocks produce no probe record. No measured checks means no uptime value. The trend preserves bucket extrema and does not join successful points across failures, internal errors, or gaps over 75 seconds. Timeline segments summarize recorded checks. Selecting one lists its exact checks and their original timestamps.

The latency histogram uses fixed millisecond bins with an open-ended final bin. It displays median with at least 2 measurements, p95 with 20, and p99 with 100, using continuous linear interpolation. Incident activity distinguishes an overlap with the selected window from opening and resolution events inside it. Average recovery includes automatic recoveries only.

Apply additive migration `20261123_05` before enabling analytics on a maintained PostgreSQL installation. It adds the `(endpoint_id, checked_at, id)` history index used for time windows and cursor paging. The migration does not change records or add columns.

```bash
python -m app.serve --reload
```

Backend: http://127.0.0.1:8000

API documentation: http://127.0.0.1:8000/docs

### 6. Start the frontend

Open another terminal:

```bash
cd frontend
npm install
npm run dev
```

Frontend: http://localhost:5173

### Live updates

The dashboard and endpoints page refresh after a manual or scheduled check commits. The browser authenticates the WebSocket in its first message and refreshes again after reconnecting. PostgreSQL `LISTEN` and `NOTIFY` deliver updates across API workers. Each worker needs a session-capable PostgreSQL connection for `LISTEN`.

For deployment, set `VITE_API_BASE_URL` to the public API base URL when building the frontend and set `FRONTEND_ORIGINS` to a JSON list of allowed browser origins on the backend. Serve the app and API over HTTPS and forward WebSocket upgrades through the reverse proxy.

### Scheduled checks and capacity

Each active endpoint has one durable due time. APScheduler polls for due work every second. PostgreSQL advisory locks limit the cluster to four scheduled probes by default, and an endpoint lease and claim ID coordinate recovery. Each result, its schedule advance, and its notification commit together. An abandoned claim becomes eligible after 45 seconds. Missed intervals are counted and coalesced into one pending check. Manual checks leave the schedule alone.

The Endpoints page shows the next due time, overdue checks, last start delay, probe duration, and coalesced intervals. The 30-second interval is a target. For planning, four workers provide 120 worker-seconds per 30-second window. Using one second of polling overhead per job, probe durations of 1, 2, 5, and 10 seconds support roughly 60, 40, 20, and 10 endpoints respectively before database overhead.

Use the same `SCHEDULED_PROBE_WORKERS` value on all API workers. Budget one database connection per active scheduled slot plus API and listener headroom. Tune `DATABASE_POOL_SIZE` and `DATABASE_MAX_OVERFLOW` per process alongside the worker count. PostgreSQL session-level locks require a session-capable connection. Measure probe and commit latency before raising capacity.

## Running Tests

With the backend dependencies installed, the fast suite can run against in-memory SQLite with a temporary outbox. Use Bash and run these commands from the repository root.

```bash
repo="$PWD"
scratch="$(mktemp -d)"
(
  cd "$scratch"
  export PYTHONPATH="$repo" DATABASE_URL=sqlite://
  export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
  export EMAIL_DELIVERY=outbox EMAIL_OUTBOX_DIR="$scratch/outbox"
  export MONITORING_RETENTION_ENABLED=false
  python -m pytest -q "$repo/tests"
)
```

The PostgreSQL integration cases are opt-in locally. To run them with the same settings as CI, start a fresh PostgreSQL 17 container with a disposable database and role both named `tracegrid_ci`. Set `TRACEGRID_CI_POSTGRES_PASSWORD` to the synthetic password used to initialize that container. Publish its port 5432 to a random loopback port and export that number as `TRACEGRID_CI_POSTGRES_PORT`. The tests reject port 5432 and require a database marker before writing.

```bash
export TRACEGRID_CI_POSTGRES_PASSWORD="$(python -c 'import secrets; print(secrets.token_hex(20))')"
export POSTGRES_PASSWORD="$TRACEGRID_CI_POSTGRES_PASSWORD"
container="$(docker run --rm -d -p 127.0.0.1::5432 -e POSTGRES_PASSWORD \
  -e POSTGRES_USER=tracegrid_ci -e POSTGRES_DB=tracegrid_ci postgres:17)"
unset POSTGRES_PASSWORD
for attempt in {1..30}; do
  docker exec "$container" pg_isready -q -h 127.0.0.1 -U tracegrid_ci -d tracegrid_ci && break
  sleep 1
done
export TRACEGRID_CI_POSTGRES_PORT="$(docker port "$container" 5432/tcp | cut -d: -f2)"
docker exec "$container" psql -X -w -v ON_ERROR_STOP=1 -U tracegrid_ci -d tracegrid_ci \
  -c "COMMENT ON DATABASE tracegrid_ci IS 'TraceGrid disposable CI database'"
DATABASE_URL="postgresql+psycopg2://tracegrid_ci:${TRACEGRID_CI_POSTGRES_PASSWORD}@127.0.0.1:${TRACEGRID_CI_POSTGRES_PORT}/tracegrid_ci" \
  python -m alembic upgrade head
```

Run the earlier pytest block with both `TRACEGRID_CI_POSTGRES_*` variables exported. Retire the disposable database when the tests finish.

```bash
docker stop "$container"
unset TRACEGRID_CI_POSTGRES_PORT TRACEGRID_CI_POSTGRES_PASSWORD
```

Run the frontend checks with Node.js 24.

```bash
cd frontend
npm ci --no-audit --no-fund
npm test
npm run lint
VITE_API_BASE_URL=http://127.0.0.1:8000 npm run build
npm audit --omit=dev --audit-level=moderate
npm audit --audit-level=high
```

## Continuous Integration

[TraceGrid CI](.github/workflows/ci.yml) runs on pushes to `main`, pull requests targeting `main`, and manual dispatch by maintainers. A newer run supersedes older runs for the same branch or pull request. Three independent jobs run on GitHub-hosted Ubuntu runners.

| Check | What it verifies |
| --- | --- |
| Backend (Python 3.12 / PostgreSQL 17) | Installs `requirements.txt`, migrates a fresh PostgreSQL database through `20261123_06`, and runs pytest. The fast suite covers account security, ownership, monitoring, WebSockets, incidents, notifications, analytics, and network safeguards. PostgreSQL cases verify the migrated schema, a synthetic legacy upgrade, account requests, shared rate limits, scheduler locks, and retention. |
| Frontend (Node.js 24) | Installs the lockfile with `npm ci`, runs Node tests and ESLint, builds the Vite production bundle, and audits npm dependencies. |
| Repository safety | Checks tracked paths and Git ignore rules with `python scripts/ci/check_tracked_paths.py`, validates workflows with `actionlint`, and scans the Git history reachable from the tested commit with Gitleaks. Scanner output is redacted. |

Open the failing job to locate the first failed step. Migration failures should be reproduced on a fresh PostgreSQL 17 container. The backend job also audits the installed Python environment, including its test dependencies, with PyPA `pip-audit` in strict mode. To run the same check locally, use an isolated Python 3.12 virtual environment with `pip==26.3` and install `requirements.txt`. Install `pip-audit==2.10.1` in a second environment and run `pip-audit --strict --progress-spinner off --path <backend-site-packages>`.

The npm runtime audit blocks moderate and higher findings. The full lockfile audit reports every advisory and blocks high and critical findings. The lockfile currently includes the moderate [minimatch advisory GHSA-g3hv-75wg-m249](https://github.com/advisories/GHSA-g3hv-75wg-m249) through ESLint. It affects development lint tooling. The patched minimatch major is outside the current tooling ranges, so CI reports it pending a compatible upstream update. Review advisory-service failures and rerun transient failures before merging.

The workflow grants read-only repository access and uses ordinary `pull_request` events. The database, signing key and outbox are disposable. The jobs use synthetic configuration, leave retention disabled, and publish no application artifacts. Deployment is a separate release activity and requires an explicit production configuration, migration rehearsal, and rollback plan.

To protect `main`, require pull requests and passing results from **Backend (Python 3.12 / PostgreSQL 17)**, **Frontend (Node.js 24)**, and **Repository safety**. Require the branch to be up to date before merging and require a review for workflow changes.

## Project Status

TraceGrid includes scheduled monitoring, account management, incidents, analytics and retention controls.

## Author

**Vishwa Teja Pathipaka**

GitHub: https://github.com/VishwaTejaPathipaka
