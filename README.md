# CIDMS

Billing for diagnostic centres, OPDs and clinics, with test reports and imaging built in and switched off for now.
One app serves many centres ("clients"). Each centre has its own address (`<client>.<domain>`), staff, settings and
data; platform staff run the product from `admin.<domain>`.

- **Backend:** FastAPI (Python 3.11), PostgreSQL 16 with row-level security, a Postgres-backed job worker.
- **Screens:** Svelte 5 + TypeScript (Vite), a single-page app served by FastAPI from the same address.
- **Production:** one server (Oracle Cloud, ARM) running Docker Compose: Postgres, the app, the worker and Caddy
  (HTTPS for every address). A push to `main` is tested and deployed by GitHub Actions.

---

## Contents

1. [What it does](#what-it-does)
2. [Security](#security)
3. [Run it locally](#run-it-locally)
4. [Configuration](#configuration)
5. [Commands](#commands)
6. [Tests and checks](#tests-and-checks)
7. [Deploying](#deploying)
8. [Running the server](#running-the-server)
9. [Dependencies](#dependencies)
10. [Project layout](#project-layout)

---

## What it does

Two switches in `web/src/lib/features.ts` hide the parts that are on hold:

| Switch | Now | What it covers |
| --- | --- | --- |
| `testReports` | **off** | report editor, DICOM viewer, WhatsApp sending, patient QR links, "My signature", `/test-reports` |
| `worklist` | **off** | the lab worklist; while off, each test is marked Pending / Ready / Delivered on its bill |

The switches only hide screens; the server's routes for those parts stay available.

### Front desk

- **New bill** (`/bills/new`). Find or add the patient, pick the referring doctor, tick tests, take the payment.
  - Prices come from the catalogue and the server works out every total.
  - Discount as a percentage or in rupees, up to the centre's limit (20% by default). Going over needs
    `billing.discount_over_limit` and notifies the owner.
  - The summary waits until a test is added; "paid now" can't be more than the total.
  - A bill can be saved on hold. Unsaved work is kept as a draft on that computer for 7 days, with "Clear draft".
  - Bill numbers run per centre and financial year (`SHC/2026-27/000123`). Saving twice (a retry, a double click)
    makes one bill (`Idempotency-Key`).
  - Keyboard: Ctrl+Enter saves, Ctrl+P saves and prints.
- **Bills** (`/bills`). Search and filters kept in the address, endless scrolling, exports to Excel and PDF, and
  "Bills by doctor" (a summary sheet plus one sheet per referring doctor).
- **A bill** (`/bills/:id`). Payments (cash, UPI, card, bank, other) and refunds with a reason; money received is
  never edited or deleted. Hold, confirm, or cancel with a reason (a bill is never deleted). Tests can be changed
  while it's on hold. Each test's report is marked pending, ready or delivered. Print view at `/bills/:id/print`.
- **Dues** (`/dues`). A workbook: a summary by referring doctor and one sheet per doctor, oldest first, with print
  and Excel. A dues digest goes to the owner every Monday at 9:00.
- **Patients** (`/patients`, `/patients/:id`). Search by name, mobile or patient number; family members sharing a
  mobile are shown so nobody is added twice. Mobiles are stored in international form.

### Working offline

When the internet drops, the desk keeps working:

- Screens opened before show their last saved copy, with a banner saying when it was saved.
- New bills get a provisional number (`OFF-K7Q-0003`) and print straight away. Payments wait in an outbox. Both
  are sent by themselves, oldest first, when the connection is back. The server refuses bills older than 30 days,
  flags duplicates, and asks before accepting a total that changed with the catalogue.
- Everything kept on the computer is in IndexedDB, encrypted with AES-GCM under a key the page can't export. It is
  removed when the person signs out (except bills and payments not yet sent).
- `/bills/offline` shows what is saved and waiting. The app can be installed (it is a PWA).

### Reports and figures

- **Dashboard** (`/`). Today's figures for everyone; turnover only for people with `analytics.view`.
- **Analytics** (`/analytics`). Trends, a heatmap, departments, tests, doctors, patients, dues, staff and a live
  "today" view.
- **Billing reports** (`/reports`). Collection, Payments, Dues, Discounts, Tests, Departments, Referring doctors and
  Staff, by day, week, month or year, each as a screen, PDF or Excel, plus one workbook with every report. Every
  export is written to the activity log.

### Catalogue

- **Tests & prices** (`/tests`, with Departments and Test types tabs) and **Doctors & hospitals** (`/doctors`).
- Items are switched off, never deleted. A new price applies to new bills only.
- **Add several:** fill a grid, paste from a spreadsheet, or import an Excel/CSV file. Every row is checked first;
  nothing is added unless all of them are valid.

### Settings and staff

- **Your account:** profile and picture, password, email, light or dark theme, which notifications to get.
- **Centre:** name, tagline, brand colour, logo and wide logo, contact details, discount limit.
- **Staff:** add people (they get a one-time temporary password and choose their own), edit, switch off, reset a
  password. Built-in roles: Owner, Centre admin, Receptionist, Technician, Doctor / radiologist, Accounts.
- **Activity log:** sign-ins, failures, exports and every change, append-only.
- **Backups:** the centre's own backups (see [Backups](#backups)).
- **API & integrations:** API keys for other systems (see [Integration API](#integration-api)).

### Platform (`admin.<domain>`)

- **Clients:** add a centre, change its plan, suspend or reactivate it, and back it up or restore it.
- **Platform staff:** Platform owner and Platform support.
- **Backups:** the whole database (see [Backups](#backups)).

### Notifications

A bell in the top bar and `/notifications`, updated live (Server-Sent Events, woken by Postgres `LISTEN/NOTIFY`).
Kinds include cancelled bills, refunds, discounts over the limit, new staff, password resets, finished exports,
failed jobs, the daily summary (21:00) and the weekly dues digest.

### Integration API

`/api/v1` (docs at `/api/v1/docs` outside production) for other systems: patients, tests, orders, reports and
their PDFs, studies, doctors. No financial fields are ever returned.

- Keys look like `sdms_live_<prefix>_<secret>`; only a SHA-256 is stored. Each key has scopes (`patients:read`,
  `tests:read`, `orders:read`, `reports:read`, `images:read`, `doctors:read`), optional allowed IPs and an expiry.
- Send it as `Authorization: Bearer <key>` or `X-API-Key: <key>`. 600 requests a minute per key.

### On hold (built, switched off)

- **Test reports:** draft → finalise → sign → amend with a reason, every version kept; templates, doctors'
  signatures, an A4 PDF, typed findings or an uploaded PDF.
- **Imaging:** DICOM upload to Orthanc, the OHIF viewer at `/viewer`, a DICOMweb proxy that only serves the centre's
  own studies. Orthanc and OHIF are in the local `docker-compose.yml` only, not in production.
- **WhatsApp:** report PDFs sent through the WhatsApp Business Cloud API (off unless `WHATSAPP_PROVIDER=meta`).
- **Patient links:** a QR code on the report opens `/r/<token>` after a check (last 4 digits of the mobile, year of
  birth or part of the bill number). The server side exists; the page isn't routed yet.
- **Custom roles:** the server side exists (`/api/roles`); the Roles screen isn't wired in yet.

---

## Security

| Area | How | Where |
| --- | --- | --- |
| Centres kept apart | Postgres row-level security on every client table. The app connects as `supreme_app` (can't bypass it); each transaction declares its centre. | `migrations/versions/0001_foundation.py`, `app/core/db.py`, `tests/test_isolation.py` |
| Which centre | Decided by the address (`<client>.<domain>`); a session only works at its own centre's address. | `app/core/tenancy.py` |
| Sessions | Random token in an HttpOnly, SameSite=Lax cookie (`__Host-sdms_session`, Secure, in production); only its hash is stored. Idle and absolute timeouts; signing out revokes it on the server. | `app/core/security.py` |
| CSRF | Every change sends `X-CSRF-Token`, plus a same-site Origin/Referer check. | `app/core/security.py` |
| Passwords | Argon2id. Old Laravel bcrypt hashes are accepted once and rehashed. At least 10 characters plus a strength check; 5 wrong tries lock the account for 15 minutes; a temporary password must be changed; changing it signs out other browsers. | `app/core/passwords.py` |
| Rate limits | Kept in the database, so all app processes share them: sign-in 20 per 5 min per IP, reset emails 3 per 15 min per address, API keys 600 a minute, and more. | `app/core/limits.py` |
| Request size | JSON 1 MB, pictures 2.1 MB, upload pieces 4 MB, DICOM up to `IMAGING_MAX_UPLOAD_MB`. | `app/core/limits.py` |
| Encrypted bodies | Request and response bodies are encrypted end to end on top of HTTPS: ECDH P-256 → HKDF-SHA256 → AES-256-GCM, a key per browser tab. `PAYLOAD_ENCRYPTION=required` refuses plain JSON. | `app/core/payload.py`, `web/src/lib/payload.ts` |
| Headers | Strict CSP (`script-src 'self'`), `frame-ancestors 'none'`, nosniff, Referrer-Policy, Permissions-Policy, HSTS in production, `no-store` on the API and pages. Fonts are self-hosted. | `app/main.py` |
| Other | Idempotency keys on bills and payments; report HTML sanitised; uploaded pictures re-encoded; API docs off in production; production refuses development passwords and weak secrets; images pinned by digest; Python packages installed with `--require-hashes`; the container runs as an unprivileged user; `pip-audit` and `npm audit` in CI. | |

Every API error has the same shape, `{message, field?, detail?, request_id}`. Unexpected errors are logged with a
stack trace and answered without internals. Logs are JSON lines with the request ID, centre, person, path, status
and time taken; people see the request ID as a "Reference" to quote. A crash in a screen shows a fallback for that
screen only and is reported to `/api/client-errors`.

---

## Run it locally

Needs Docker Desktop, Python 3.11 and Node 20 or later.

```sh
docker compose up -d postgres              # Postgres on localhost:5433
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt
cp .env.example .env
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m app.seed --supreme # roles, plans, platform owner, Supreme Health Care
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000

cd web && npm install && npm run dev       # in a second terminal (Vite passes /api to port 8000)
```

| Address | Who | First sign-in |
| --- | --- | --- |
| http://supreme.localhost:5173 | Supreme Health Care staff | `owner@supreme.local` / `Change-me-now-1` |
| http://admin.localhost:5173 | Platform staff | `owner@supremedms.local` / `Change-me-now-1` |

Both are asked to choose a new password at first sign-in. Edge and Chrome send every `*.localhost` address to this
machine, so nothing else needs setting up. To use FastAPI alone, run `cd web && npm run build` and open port 8000.

Optional services in `docker-compose.yml`:

```sh
docker compose up -d orthanc ohif                    # imaging (Orthanc on 8042, OHIF on 3005)
docker compose --profile worker up -d worker         # the background worker in Docker
docker compose --profile legacy up -d legacy         # the old app's MariaDB (port 3307), for the data import
```

Without the worker, run it yourself: `.venv/Scripts/python -m app.worker`.

---

## Configuration

Settings come from environment variables (or `.env`); the names match `app/core/config.py` in upper case.
`.env.example` is for development, `deploy/env.production.example` for the server.

| Variable | Default | Meaning |
| --- | --- | --- |
| **General** | | |
| `ENVIRONMENT` | `production` | `development`, `test` or `production` |
| `APP_NAME` | `CIDMS` | |
| `LOG_LEVEL` | `INFO` | |
| `DISPLAY_TIMEZONE` | `Asia/Kolkata` | times are stored in UTC and shown in this zone |
| **Database** | | |
| `DATABASE_URL` | `…supreme_app…@localhost:5433/supreme` | the app's role (row-level security applies) |
| `MIGRATION_DATABASE_URL` | `…supreme_owner…@localhost:5433/supreme` | the owner role, for migrations and imports |
| `DB_STATEMENT_TIMEOUT_S` | `30` | |
| `DB_IDLE_IN_TRANSACTION_TIMEOUT_S` | `60` | |
| **Addresses** | | |
| `BASE_DOMAIN` | `localhost` | centres are `<slug>.<BASE_DOMAIN>` |
| `PLATFORM_SUBDOMAIN` | `admin` | |
| **Sessions and sign-in** | | |
| `SESSION_SECRET` | dev value | 32+ random characters in production |
| `SESSION_IDLE_MINUTES` | `480` | |
| `SESSION_ABSOLUTE_DAYS` | `30` | with "Remember me" |
| `SESSION_BROWSER_HOURS` | `12` | without it |
| `PASSWORD_RESET_MINUTES` | `30` | |
| `MAX_FAILED_LOGINS` / `LOCKOUT_MINUTES` | `5` / `15` | |
| `MIN_PASSWORD_LENGTH` | `10` | |
| **Email** | | |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD` | empty, `587` | empty host: reset links go to the log |
| `MAIL_FROM` | `CIDMS <no-reply@localhost>` | |
| **Files** | | |
| `STORAGE_DIR` | `storage` | job files and centre backups |
| `BACKUP_DIR` | `backups` | the server's database backups (read-only to the app) |
| **Security** | | |
| `PAYLOAD_ENCRYPTION` | `optional` | `off`, `optional` or `required` |
| `REPORT_LINK_SECRET` | empty | signs patient links; empty uses `SESSION_SECRET` |
| `REPORT_LINK_DAYS` | `90` | |
| **Monitoring** | | |
| `ALERT_EMAIL` | empty | comma-separated; empty: alerts are only logged |
| `SENTRY_DSN` | empty | no personal data is sent |
| `WORKER_ALIVE_FILE` | `/tmp/cidms-worker-alive` | the worker's health check |
| **Imaging** (on hold) | | |
| `ORTHANC_URL`, `ORTHANC_USER`, `ORTHANC_PASSWORD` | local values | |
| `OHIF_URL` | `http://127.0.0.1:3005` | |
| `IMAGING_MAX_UPLOAD_MB` | `500` | |
| `REPORT_TARGET_HOURS_IMAGING` / `_OTHER` | `24` / `48` | when a report counts as overdue |
| **WhatsApp** (on hold) | | |
| `WHATSAPP_PROVIDER` | empty | empty = off, or `meta` |
| `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_TEMPLATE`, `WHATSAPP_TEMPLATE_LANG`, `WHATSAPP_API_VERSION`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET` | | |
| **Seed** | | |
| `SEED_PLATFORM_OWNER_EMAIL` / `_PASSWORD` | `owner@supremedms.local` / `Change-me-now-1` | refused in production |
| `SEED_SUPREME_OWNER_EMAIL` / `_PASSWORD` | `owner@supreme.local` / `Change-me-now-1` | |

Read elsewhere: `WORKER_CONCURRENCY` (worker, default 2), `RCLONE_REMOTE` (off-site copies in `deploy/backup.sh`),
`APP_VERSION` (set by CI), `TEST_DB` and `BROWSER_CHANNEL` (tests). Production also needs `ACME_EMAIL`,
`POSTGRES_OWNER_PASSWORD` and `POSTGRES_APP_PASSWORD` (used by Compose and Caddy).

---

## Commands

| What | Command |
| --- | --- |
| Migrations | `python -m alembic upgrade head` |
| Reference data | `python -m app.seed` (permissions, roles, plans, platform owner) |
| … plus Supreme Health Care | `python -m app.seed --supreme` |
| … roles only (safe on a live server) | `python -m app.seed --roles-only` |
| Worker | `python -m app.worker [--concurrency N] [--poll SECONDS] [--kinds a,b] [--once] [--no-scheduler]` |
| Add someone by hand | `python -m app.manage create-user --workspace <slug or platform> --email … --name … --role …` |
| Import the old app's data | `python -m app.legacy_import [--dry-run] [--tenant supreme] [--legacy-url mysql+pymysql://…]` |

The worker runs jobs from a Postgres queue (`FOR UPDATE SKIP LOCKED`): exports, backups and restores of centres,
notifications, the daily summary (21:00), the dues digest (Mondays 09:00) and the nightly clean-up (03:30). It
stops cleanly on SIGTERM and picks up jobs left by a crashed worker after 10 minutes.

The legacy import runs in one transaction and can be run again safely (it matches on the old ids). It writes a
report, issues, doctors and a reconciliation to `storage/import/<date-time>/`, and exits 0 when the figures
reconcile, 1 when they don't, 2 when it stopped.

---

## Tests and checks

```sh
.venv/Scripts/python -m pytest              # needs the Docker Postgres
.venv/Scripts/python -m ruff check .
cd web && npm run check                     # Svelte and TypeScript
```

- Tests run against `supreme_test` (made by `docker/postgres/01-roles.sh`); set `TEST_DB` to use another
  database so two runs don't clash.
- They cover sign-in, isolation between centres, billing, reports, analytics, imports, backups, jobs and
  notifications, rate limits, payload encryption, API keys, roles and test reports.
- `tests/test_browser.py` drives the real screens in Microsoft Edge (`BROWSER_CHANNEL=msedge`, the default) or
  Chromium (`python -m playwright install chromium`, then `BROWSER_CHANNEL=chromium`). It needs `cd web && npm run
  build` first and skips itself otherwise.
- `tests/test_legacy_import.py` does a full dry run only when the legacy MariaDB is running.

---

## Deploying

### Releases

Work happens on a feature branch, is merged into `dev`, and released by merging `dev` into `main`. Every push to
`main` runs CI and, if everything passes, deploys:

| Job | What it checks |
| --- | --- |
| Server | ruff, pytest against a real Postgres, `pip-audit` |
| Screens | `svelte-check --fail-on-warnings`, the build, `npm audit` |
| Browser | the browser tests in Chromium |
| Deploy | uploads the code, builds `supreme-dms:<commit>`, runs migrations, restarts, runs `app.seed --roles-only`, checks `https://admin.<domain>/readyz` |

Only one deploy runs at a time. A failed run is fixed with a new commit, not by re-running it: re-running an old
run on `main` cancels a newer one that's in progress.

GitHub secrets: `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_DOMAIN`, and `DEPLOY_HOST_KEY` (the server's
SSH host key, from `ssh-keyscan -t ed25519 <host>`; without it CI trusts whatever key answers and warns).

### A new server

1. Write the production settings (random database passwords and session secret):
   `deploy/make-env.ps1 -Domain cidms.example.com -Email you@example.com`
2. First deploy (installs Docker, the firewall, swap and the backup schedule on the server):
   `deploy/deploy.ps1 -Ip <server ip> -Key <ssh key> -FirstTime` (add `-MoveData` to copy the local database across)
3. Point `*.<domain>` and `<domain>` at the server. Caddy gets a certificate for each address the first time it is
   opened, only after the app confirms it is a real centre or the platform (`/internal/tls-allowed`).

After that, releases go through CI. `.env.production` stays on the server and is never in git or GitHub.

### What runs on the server

`deploy/docker-compose.prod.yml`, in `/opt/supreme-dms`:

| Service | Role |
| --- | --- |
| `postgres` | the database, no public port |
| `migrate` | `alembic upgrade head`, then exits; the app waits for it |
| `app` | uvicorn with 3 workers behind Caddy |
| `worker` | the job worker; healthy while it touches its alive file every 30 s |
| `caddy` | HTTPS on 80/443 (HTTP/3 too), compression, the live stream unbuffered, HSTS |

---

## Running the server

### Health

- `/healthz`: the app is up (no database check); used by Docker's health check and the screens' connection check.
- `/readyz`: the app can reach the database; `503` with `Retry-After` when it can't. Point uptime monitoring here.

### Backups

- **Whole database (platform):** `deploy/backup.sh` runs from cron every 5 minutes and backs up when the schedule
  set in the platform's Settings > Backups says it's due. Each copy is a `pg_dump` (`.dump`, checked with
  `pg_restore --list`) plus a `.sql.gz`, kept in `/opt/supreme-dms/backups` for the chosen number of days and
  copied off the server with rclone when `RCLONE_REMOTE` is set. Copies can be downloaded from the platform.
- **Restoring the whole database:** from the platform's Backups screen, or on the server with
  `deploy/restore.sh <file>` (asks you to type RESTORE). It first saves a safety copy, then restores, migrates,
  restarts and signs everyone out.
- **One centre:** each centre's owner sets its own schedule (daily at 23:30, kept 30 days by default). The worker
  writes `storage/client-backups/<centre>/…cidms.json.gz`, downloadable as the backup file, Excel or SQL, and
  restorable from the same screen. Staff, roles, API keys, the activity log and sessions aren't included.

### Rolling back

Each deploy is kept as the image `supreme-dms:<commit>` (the last five) and recorded in
`/opt/supreme-dms/releases.log`. On the server, `sudo deploy/rollback.sh` switches the app and worker back to the
previous version (or `sudo deploy/rollback.sh <commit>` to a named one). The database is left as it is.

---

## Dependencies

Exact versions are locked. Add or change a package in `requirements.in` (the app) or `requirements-dev.in`
(tests and tools), then regenerate the locks inside Linux, as the server runs it:

```sh
docker run --rm -v "$PWD:/src" -w /src python:3.11-slim sh -c "pip install pip-tools==7.6.2 && \
  pip-compile --generate-hashes --allow-unsafe --strip-extras -o requirements.txt requirements.in && \
  pip-compile --allow-unsafe --strip-extras -c requirements.txt -o requirements-dev.txt requirements-dev.in"
```

uvloop doesn't exist for Windows: after regenerating, add ` ; sys_platform != "win32"` to its line in both files
(right after the version), so installs on Windows keep working. Don't run `pip-compile` on Windows: it drops
uvloop from the lock.

`requirements.txt` carries checksums (the Docker image installs with `--require-hashes`); `requirements-dev.txt`
has the same versions without them. Docker images are pinned by digest in `Dockerfile`, `docker-compose.yml` and
`deploy/docker-compose.prod.yml`.

---

## Project layout

```
app/
  api/            routes, HTTP only (auth, billing, reports, analytics, catalogue_import, centre, staff, roles,
                  platform, client_backups, notifications, uploads, payload, integrations, v1, test_reports, system, dev)
  services/       business rules (billing, patients, catalogue, reports, exports, analytics, staff, roles, clients,
                  backups, client_backups, notifications, integrations, uploads, test_reports, imaging, whatsapp, …)
  repositories/   database queries (users, counters)
  core/           settings, database and centre scope, security, tenancy, passwords, payload encryption, limits,
                  jobs, logging, errors, mail, alerts, storage, money, phone, HTML cleaning, idempotency
  jobs/           what the worker runs (exports, backups, summaries, clean-up)
  main.py         the app: middleware, routes, error handlers, serving web/dist
  models.py       tables              catalog.py   permissions and roles
  seed.py  manage.py  worker.py  legacy_import.py
migrations/       Alembic: tables and row-level security policies (0001_foundation … 0019_rate_limits)
web/
  src/lib/        api client, session, router, forms, payload encryption, offline store, outbox, uploads, drafts
  src/components/ shared parts: DataTable, FilterBar, Dialog, Field, charts, Workbook, Spreadsheet, …
  src/pages/      screens: bills/, catalogue/, patients/, reports/, settings/, platform/, dashboard, analytics
  src/styles/     theme, global styles, phone layout
  public/         icons, web app manifest, service worker
tests/            pytest, including the browser tests
deploy/           production Compose file, Caddyfile, deploy, backup, restore and rollback scripts
docker/           Postgres roles and test database, OHIF settings
```
