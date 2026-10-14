# Don't Queue

A multi-tenant, server-rendered queue management platform. Organizations create
branches and services; every service gets a live queue that staff operate and
customers can join remotely from a public page.

Built with **Django + the ORM**, **Django templates**, and **plain HTML/CSS/JS** —
no SPA framework, no CSS framework, no external paid services required.

## Highlights

- **Multi-tenant** — every branch, service, customer and entry belongs to exactly
  one organization. Access is enforced on the server for every request.
- **Roles** — platform admin, owner, admin, branch manager, receptionist/provider.
- **Queue engine** — a strict state machine, append-only event history, and an
  append-only audit log. Ticket numbers are allocated with portable
  compare-and-set loops (SQLite and PostgreSQL), so no row locks are required.
- **Public flow** — customers join from a link and watch a status page that polls
  for position and an approximate wait estimate.
- **Notifications** — provider-based (in-app, email, console) so local
  development needs no credentials.
- **Auth** — signup, sign-in, invitations, and a full password-reset flow.

## Quickstart

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo       # optional: creates a ready-to-explore org
python manage.py runserver
```

Then visit:

- `http://127.0.0.1:8000/` — marketing landing page
- `http://127.0.0.1:8000/explore/` — public organization search
- `http://127.0.0.1:8000/auth/signup/` — create an account and organization

`seed_demo` creates a demo organization with sample queues:

- Public join: `/o/demo-clinic/join/`
- Login: `demo@dontqueue.local` / `demo12345!`

Re-run with `python manage.py seed_demo --reset` to start the demo clean.

## Configuration

Settings are environment driven (see `.env.example`). Copy it to `.env` to
override defaults. The same code runs locally (SQLite) and in production
(PostgreSQL) — set `POSTGRES_DB` and friends to switch databases.

| Variable | Purpose | Default |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | Signing key | insecure dev key |
| `DJANGO_DEBUG` | Debug mode | `true` |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hosts | `localhost,127.0.0.1,[::1],testserver` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Comma-separated origins | empty |
| `DJANGO_TIME_ZONE` | Server time zone | `UTC` |
| `POSTGRES_DB` | Enables PostgreSQL when set | empty (SQLite) |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` | Postgres credentials | `postgres` / empty |
| `POSTGRES_HOST` / `POSTGRES_PORT` | Postgres host / port | `localhost` / `5432` |
| `POLL_INTERVAL_SECONDS` | Public status polling interval | `8` |
| `NOTIFICATION_DEFAULT_CHANNELS` | Default channels | `inapp` |

## Roles

| Role | Can do |
| --- | --- |
| Platform admin | Reach the platform console across organizations |
| Owner / Admin | Configure branches, services, rules, team, and billing-style settings |
| Branch manager | Operate queues and see branch-scoped data |
| Receptionist / Provider | Register walk-ins and operate the queue console |
| Customer | Join a queue and watch status — no account required |

## URL map

| Path | Description |
| --- | --- |
| `/` | Landing page |
| `/explore/` | Public organization search |
| `/auth/*` | Signup, sign-in, onboarding, profile, password reset |
| `/o/<slug>/join/` | Public join page for an organization |
| `/o/<slug>/t/<reference>/` | Public ticket status (+ `status.json`) |
| `/app/o/<slug>/` | Organization dashboard (`+ branches, services, staff, team, audit`) |
| `/app/o/<slug>/console/<queue>/` | Operator console |
| `/platform/` | Platform console (platform admins) |
| `/healthz` | Health check |
| `/admin/` | Django admin |

## Project layout

```
accounts/       identity, tenancy, memberships, invitations
directory/      branches, services, staff assignments, queue rules
queues/         queues, customers, entries, events + the service layer engine
notifications/  provider-based notification delivery
audit/          append-only audit log
core/           landing, explore, dashboards, permissions, middleware, seed
templates/      server-rendered templates
static/         theme CSS and fonts
```

## Testing

The queue engine and end-to-end workflows are exercised with Django's test
client. Run the suite with:

```bash
python manage.py test
```

## Deployment

1. Set `DJANGO_DEBUG=false` and a strong `DJANGO_SECRET_KEY`.
2. Point the database at PostgreSQL via the `POSTGRES_*` variables.
3. Run `python manage.py migrate` and `python manage.py collectstatic`.
4. Serve with a WSGI server (e.g. `gunicorn dontqueue.wsgi`) behind a TLS
   proxy. Configure email by replacing the console mailer in
   `dontqueue/settings.py` with a real backend.
