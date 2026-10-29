# CIDMS

**CIDMS runs the front desk of a diagnostic centre, OPD or clinic: billing, patients, doctors, reports and
figures, in one place.** One installation serves many centres ("clients") — each with its own address
(`<client>.<domain>`), staff, settings and data, kept completely apart from every other centre. Platform staff
oversee every centre from `admin.<domain>`.

Built for how a real front desk works: a bill made in seconds, nothing lost when the internet drops, and numbers
the owner can trust at the end of the day.

---

## A walk through the app

### Front desk

Making a bill is the one thing the desk does all day, so it's built to be fast:

- **New bill.** Find the patient (or add one in a few fields — a family member sharing a mobile number is shown
  so nobody is registered twice), pick the referring doctor or leave it as Self, tick off tests from the
  catalogue. Prices and totals are worked out automatically; a discount can be a percentage or a flat amount, up
  to the centre's limit, with the owner notified if someone goes over it.
  - Unsaved work is kept as a draft on that computer for a week, so a closed tab or a browser crash costs nothing.
  - Bill numbers run per centre and financial year (`SHC/2026-27/000123`); saving twice by accident — a slow
    network, a double click — still makes only one bill.
  - Ctrl+Enter saves, Ctrl+P saves and prints.
- **Bills.** Every bill, searchable and filterable, with endless scrolling and exports to Excel and PDF —
  including "Bills by doctor", a summary sheet plus one sheet per referring doctor.
- **A bill.** Take payments (cash, UPI, card, bank, other) or give a refund with a reason; money received is
  never edited or deleted after the fact. Put a bill on hold, confirm it or cancel it with a reason — a bill is
  never simply deleted. Each test on it is tracked as pending, ready or delivered.
- **Dues.** Everything still owed, oldest first, grouped by referring doctor — read on screen, printed, or
  downloaded as Excel. The owner gets a dues digest by email every Monday morning.
- **Patients.** Every patient who has ever been billed, searchable by name, mobile or patient number.

### Working offline

The desk doesn't stop when the internet does:

- Screens already opened keep showing their last saved copy, with a note on when it was saved.
- A new bill made offline gets a provisional number and prints immediately; its payment waits in an outbox.
  Everything is sent through automatically, oldest first, the moment the connection returns.
- What's kept on the computer meanwhile is encrypted, and is cleared the moment the person signs out (apart from
  anything still waiting to be sent). The app installs like a native one (it's a PWA), so it's always one tap away.

### Reports and figures

- **Dashboard.** Today's numbers for everyone at the centre; turnover for the people allowed to see it.
- **Analytics.** Trends over time, a heatmap of busy periods, and breakdowns by department, test, doctor,
  patient, dues and staff.
- **Billing reports.** Collection, Payments, Dues, Discounts, Tests, Departments, Referring doctors and Staff —
  by day, week, month or year, each as a screen, a PDF or an Excel file, or all of them together in one workbook.

### Catalogue, staff and settings

- **Tests & prices, Doctors & hospitals.** Nothing is ever deleted, only switched off, so history stays intact. A
  changed price only ever applies to new bills. A whole list can be added at once — type it into a grid, paste
  from a spreadsheet, or import a file — and every row is checked before anything is saved.
- **Staff.** Add people with a one-time password they choose their own from; built-in roles cover the Owner,
  centre admin, receptionist, technician, doctor/radiologist and accounts.
- **Centre settings.** Name, tagline, brand colour, logo, contact details and the centre's discount limit.
- **Activity log.** Every sign-in, failed attempt, export and change, kept permanently.
- **Backups.** Each centre can back itself up on its own schedule and restore from the same screen — downloadable
  as a backup file, Excel or SQL.
- **The platform** (`admin.<domain>`) adds, suspends or reactivates a centre, changes its plan, and can back up
  or restore the whole database.

### Staying in the loop

A live notification bell covers cancelled bills, refunds gone over the discount limit, new staff, password
resets, finished exports, a daily summary every evening and a weekly dues digest — updated the moment something
happens, no refresh needed.

### Connecting other systems

Other software can read a centre's patients, tests, orders, reports and doctors through a documented API, scoped
per key with optional IP restrictions and an expiry — financial details are never exposed through it.

### Built, and waiting to be switched on

A few substantial pieces are already built and tested, just switched off until they're needed: full test
reports (drafted, signed and amended with a complete history), DICOM imaging with a built-in viewer, sending
signed reports over WhatsApp, and a QR code on a printed report that lets a patient look it up themselves.

---

## Built to be trusted with the data

- Every centre's data is walled off from every other centre at the database level — not just in the app's logic.
- Passwords are never stored in a reversible form; too many wrong attempts locks the account for a while.
- Every request and response is encrypted end to end, on top of HTTPS.
- Nothing financial is silently edited or deleted — bills, payments and the activity log are append-only.
- Every export and change is recorded, with a reference number people can quote if something needs looking into.

---

## Under the hood

FastAPI and PostgreSQL on the server, Svelte on the screen, one Docker Compose stack behind HTTPS, deployed
automatically by GitHub Actions on every push to `main`. For running it locally, configuration, commands, tests
and deploying, see [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).
