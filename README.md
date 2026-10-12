# CIDMS

Billing, reports and imaging for diagnostic centres, OPDs and clinics. One app serves many clients. Each client
has its own address (`<client>.<domain>`), staff, settings and data. Platform staff run the product from
`admin.<domain>`.

The plan, including the database design, the data move and the phases, is in the CIDMS rebuild plan document.

## What's built (phase 1: foundation)

- **Clients kept apart in the database.** Every client table has Postgres row-level security. The app connects as
  `supreme_app`, a role that can't bypass it, and each transaction declares which client it is working for.
- **Sign-in with an HttpOnly session cookie.** Sessions use an HttpOnly, SameSite cookie (`__Host-` and Secure in
  production) that holds a random token; only its hash is stored. Sessions have an idle and an absolute timeout,
  and signing out revokes them on the server. Every change needs the CSRF token. A session only works at its
  own client's address.
- **Passwords.** Hashed with Argon2id. Old Laravel bcrypt hashes are accepted once and rehashed. Accounts lock
  after 5 wrong passwords, sign-in is rate-limited per IP, a temporary password must be changed at first
  sign-in, and changing a password signs out other browsers.
- **Roles and permissions.** Checked on the server for every request. The built-in roles are Owner, Centre admin,
  Receptionist, Technician, Doctor and Accounts, plus Platform owner and Platform support.
- **Errors.** Every API error has the same shape: `{message, field?, detail?, request_id}`. Unexpected errors are
  logged with a stack trace and answered without internals. In the browser, a Svelte error boundary around
  each screen shows a fallback, while the menu keeps working, and reports the crash to `/api/client-errors`.
  Uncaught errors and promise rejections are reported too.
- **Logging.** JSON lines with a request ID, client, person, path, status and duration. Request IDs are returned
  in `X-Request-ID` and shown to people as a reference. An append-only activity log in the database records
  sign-ins, failures and every change.
- **Screens.** Sign-in, choosing a new password, dashboard, staff (search, paging, add, edit, deactivate, reset
  password), centre settings (with a warning before leaving unsaved changes), and the activity log. The platform
  has its own screens for clients (add, suspend, reactivate) and platform staff. Light and dark modes are
  supported, and the screens work on a phone.

## Run it locally

Needs Docker Desktop, Python 3.11 and Node 20 or later.

```sh
docker compose up -d                       # Postgres on localhost:5433
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt
cp .env.example .env
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m app.seed --supreme # roles, plans, platform owner, Supreme Health Care
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000

cd web && npm install && npm run dev       # in a second terminal
```

Open:

| Address | Who | First sign-in |
| --- | --- | --- |
| http://supreme.localhost:5173 | Supreme Health Care staff | `owner@supreme.local` / `Change-me-now-1` |
| http://admin.localhost:5173 | Platform staff | `owner@supremedms.local` / `Change-me-now-1` |

Both accounts are asked to choose a new password at first sign-in. Edge and Chrome send every `*.localhost`
address to this machine, so nothing else needs setting up. To use only FastAPI, run `cd web && npm run build`
and open port 8000 instead.

## Checks

```sh
.venv/Scripts/python -m pytest            # API, row-level security and browser tests (needs Docker; browser tests need the build and Edge)
.venv/Scripts/python -m ruff check .
cd web && npm run check                   # Svelte and TypeScript
```

## Layout

```
app/
  api/            routes: HTTP only
  services/       business rules (sign-in, staff, clients, settings, activity)
  repositories/   database queries
  core/           settings, database and client scope, security, tenancy, logging, errors, limits
  models.py       tables        catalog.py  permissions and roles        seed.py  reference data
migrations/       Alembic (tables, row-level security policies)
web/src/          Svelte app: lib/ (api, session, router, errors), components/, pages/
tests/            pytest: auth, isolation, staff and platform, errors and logging, browser
```
