# Health Platform Backend

A working implementation of the Identity and Onboarding module specifications for the Health Platform & Digital Medicine Marketplace, built as a **modular monolith**: one deployable app and one shared database, with each module owning its own tables and a narrow, explicit contract for anything it needs from another module.

- **Identity** — registration, authentication, sessions, MFA, social login, role/permission management.
- **Onboarding** — applicant onboarding (doctors, nutritionists, hospitals, clinics, pharmacies), document review, verification checks, and maker-checker approval.

- **Language / framework:** Python 3.14, [FastAPI](https://fastapi.tiangolo.com/)
- **Database:** PostgreSQL 18
- **API docs:** auto-generated OpenAPI/Swagger UI at `/docs`, plus a checked-in static spec at [`openapi/api.yaml`](openapi/api.yaml)

See [Project layout](#project-layout) for how the two modules are structured and where the next one (Providers, Pharmacy, ...) would plug in.

---

## Quick start (Docker — recommended)

Requires only Docker and Docker Compose.

```bash
cd backend
cp .env.example .env

# Generate JWT signing keys + secrets (writes to ./keys, prints values for .env)
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"   # needed once, just for this script
.venv/bin/python scripts/generate_jwt_keys.py
# Paste the printed MFA_ENCRYPTION_KEY and TOKEN_HASH_PEPPER into .env

docker compose up --build
```

Then:

- API: <http://localhost:8000>
- Swagger UI: <http://localhost:8000/docs>
- ReDoc: <http://localhost:8000/redoc>
- Adminer (DB browser): <http://localhost:8080> — system: PostgreSQL, server: `db`, user/pass: `health_platform` / `health_platform_dev`, database: `health_platform`

The `app` container runs migrations and seeds (roles/permissions, onboarding document requirements) automatically on every start (all idempotent, so this is safe to run repeatedly) before starting the API — no separate step needed. If you ever want to run any of them by hand (e.g. after pulling schema changes without restarting the container):

```bash
docker compose exec app alembic upgrade head
docker compose exec app python -m scripts.seed_roles_permissions
docker compose exec app python -m scripts.seed_document_requirements
```

You now have a fully running backend. Try it:

```bash
curl -X POST http://localhost:8000/api/v1/auth/register/patient \
  -H "Content-Type: application/json" \
  -d '{
    "email": "ana@example.com", "password": "SecurePassword@123",
    "mobileNumber": "+258841234567", "firstName": "Ana", "lastName": "Mabote",
    "dateOfBirth": "1992-08-15", "termsAccepted": true,
    "privacyPolicyAccepted": true, "healthDataConsentAccepted": true
  }'
```

Since SMS/email are mocked by default, the verification link/OTP are printed to the `app` container's logs (`docker compose logs -f app`) instead of actually being sent — look for `[MOCK EMAIL ...]` / `[MOCK SMS ...]` lines.

---

## Quick start (without Docker)

Requires Python 3.14 (or 3.12+ — see [Python version note](#python-version-note)) and a local PostgreSQL 18 server.

```bash
cd backend

# 1. Create the database and a role for it (adjust to your local Postgres setup)
createdb health_platform
psql health_platform -c "CREATE USER health_platform WITH PASSWORD 'health_platform_dev' CREATEDB;"
psql health_platform -c "GRANT ALL ON DATABASE health_platform TO health_platform;"

# 2. Set up the virtual environment
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e ".[dev]"

# 3. Configure environment
cp .env.example .env
.venv/bin/python scripts/generate_jwt_keys.py
# Paste the printed MFA_ENCRYPTION_KEY and TOKEN_HASH_PEPPER into .env

# 4. Migrate and seed
.venv/bin/alembic upgrade head
.venv/bin/python -m scripts.seed_roles_permissions
.venv/bin/python -m scripts.seed_document_requirements

# 5. Run
.venv/bin/uvicorn app.main:app --reload
```

A `Makefile` wraps all of the above — see `make help`.

### Python version note

The project targets **Python 3.14** (the latest stable line as of writing) — that's what the `Dockerfile` uses and what's recommended for running this yourself. The code itself only uses syntax available since 3.12, so a 3.12 or 3.13 interpreter also works if that's what you have installed locally; only the Docker image is pinned to 3.14.

---

## Running the tests

Tests run against a **real PostgreSQL database** (a separate `health_platform_test` database, created and migrated automatically), not mocks — this was deliberate: every flow in both modules (registration, login, MFA, token rotation, application submission, concurrent claim, maker-checker approval, etc.) was validated end-to-end against Postgres during development, and the test suite preserves that.

```bash
# Postgres must be running and reachable the same way it is for the app
# (DATABASE_URL's host/port/credentials, just a different db name)
.venv/bin/pytest -v
```

112 tests: 69 for Identity (registration, login/lockout, token rotation & reuse detection, email/mobile verification, password change/reset, MFA, sessions, admin role/permission enforcement) and 43 for Onboarding (application lifecycle, section/completeness validation, document upload/replace/validation, concurrency-safe claiming, review + checklist, maker-checker-enforced approval/rejection, suspension, verification checks, information requests).

```bash
.venv/bin/pytest --cov=app --cov-report=term-missing   # with coverage
```

---

## API documentation

- **Interactive:** run the app and open `/docs` (Swagger UI) or `/redoc`.
- **Static file:** [`openapi/api.yaml`](openapi/api.yaml) (also available as `.json`) — generated from the live app, so it's always an exact match for the implementation. Regenerate after changing any route/schema:

  ```bash
  .venv/bin/python -m scripts.export_openapi
  ```

Every endpoint uses the `{"success": true, "data": ...}` / `{"success": false, "error": {"code", "message"}}` envelope from the spec. Try it against Swagger UI's "Authorize" button using the `accessToken` from `/auth/login`.

---

## Project layout

```
backend/
├── app/
│   ├── core/                    # cross-cutting: config, db, errors, rate limiting, idempotency,
│   │   │                          notifications, generic outbox dispatcher
│   ├── shared/                  # port interfaces + mock adapters for modules that don't exist
│   │   │                          yet but Onboarding depends on (Documents, Provider, Institution)
│   │   ├── documents/
│   │   ├── provider/
│   │   └── institution/
│   ├── modules/
│   │   ├── identity/              # registration, auth, sessions, MFA, social login, roles
│   │   │   ├── domain/              # enums, ORM models, events, exceptions, repository protocols
│   │   │   ├── infrastructure/      # SQLAlchemy repos, social provider adapters
│   │   │   ├── application/         # services, Pydantic schemas, security primitives
│   │   │   └── api/                  # FastAPI routes + dependency wiring
│   │   └── onboarding/             # applicant onboarding, review, verification, decisions
│   │       ├── domain/               # enums, 19 ORM models, workflow state machine, events
│   │       ├── infrastructure/       # SQLAlchemy repos, Identity adapter, registry adapters
│   │       ├── application/          # 9 services (one per spec section), schemas
│   │       └── api/                   # applicant + back-office routes
│   └── main.py                    # app factory, middleware, exception handlers, background tasks
├── alembic/                      # migrations
├── scripts/                      # generate_jwt_keys, seed_roles_permissions,
│                                    seed_document_requirements, export_openapi
├── tests/
├── openapi/                      # exported static spec
├── docker-compose.yml / Dockerfile
└── pyproject.toml / requirements.txt
```

**Adding the next module** (e.g. Providers): create `app/modules/providers/` following the same `domain/infrastructure/application/api` shape, add its router to a new aggregator alongside the existing two in `app/main.py`, and import its models in `alembic/env.py` so migrations pick them up. Cross-module calls into Identity go through `app.modules.identity.application.identity_ports.IdentityQueryService` / `IdentityCommandService`; calls into Onboarding would go through the equivalent `app.modules.onboarding.application.onboarding_ports` — never directly at another module's repositories or ORM models. If the new module needs something from a module that doesn't exist yet, follow the `app/shared/` pattern: a narrow Protocol plus a mock adapter, the same way `app/shared/documents`, `app/shared/provider`, and `app/shared/institution` stand in for Onboarding's dependencies today.

---

## What's implemented

### Identity

Patient/doctor registration, local + social (Google/Apple/Facebook) login, JWT access tokens (RS256) with refresh-token rotation and reuse detection, session management, email verification, mobile OTP verification, password change/forgot/reset with history checks, MFA (authenticator/TOTP with recovery codes, plus SMS/email as login-time second factors), role/permission administration, account lockout, idempotency keys on registration, and a transactional outbox for domain events.

### Onboarding

The full application lifecycle from the spec: creation with auto-generated application numbers, dynamic section/document requirement resolution (including the speciality-conditional rule for `SPECIALISATION_CERTIFICATE`), completeness calculation, submission with full precondition validation, withdrawal, document upload/confirm/replace/delete, back-office search and detail views, assignment/claim/reassign/release (claim uses real `SELECT ... FOR UPDATE` row locking — see `test_concurrent_claims_only_one_succeeds`), review lifecycle with configurable checklist templates (falling back to a sensible default), document review, server-side maker-checker-enforced approve/conditionally-approve/reject, suspension, verification checks (manual and automatic-provider paths), information requests with SLA pause/resume, risk flags that block approval, and scheduled overdue/credential-expiry processing.

Identity integration is **real, not mocked** — approval triggers a role transition (`DOCTOR_APPLICANT` → `DOCTOR`, etc.) via Identity's own `IdentityCommandService`, asynchronously through the outbox per spec section 16.2 (`application/outbox_dispatcher.py`), exactly the cross-module contract `IdentityQueryService`/`IdentityCommandService` were built for.

**Deliberately mocked / simplified for this stage:**

| Area | What's here now | Production follow-up |
|---|---|---|
| SMS delivery | Mocked (prints to console, in-memory) — per explicit instruction, no real provider chosen yet | Wire a real adapter (Twilio, Vonage, ...) behind `core/notifications.py`'s `NotificationPort` |
| Email delivery | Mocked by default; a working SMTP adapter is included (`EMAIL_PROVIDER=smtp`) | Point `SMTP_*` at a real relay, or add a provider-API adapter (SendGrid, SES, ...) |
| Documents module | In-memory mock (`app/shared/documents`) simulating presigned uploads and instant "availability" — no real file storage/malware scanning | Implement a real Documents module behind the same `DocumentPort`; Onboarding's services don't change |
| Provider / Institution modules | In-memory mocks (`app/shared/provider`, `app/shared/institution`) that record activation/suspension calls | Implement real modules behind the same ports; `DecisionService`/the outbox dispatcher don't change |
| External registry verification | Mock automatic adapter + a real `MANUAL` path (matches the spec's own example) | Implement real registry adapters behind `RegistryAdapter` (`onboarding/infrastructure/registry_adapters.py`) |
| Scheduled tasks (SLA overdue, credential expiry) | A background asyncio loop (hourly), same pattern as the outbox dispatcher | Move to a real scheduler (cron, Celery beat, ...) in production |
| Rate limiting | In-process, in-memory (correct for one instance) | Swap `InMemoryRateLimiter` (`core/rate_limit.py`) for a Redis-backed one before running >1 instance |
| Outbox dispatch | Background polling task inside the same process | Swap for the real message broker once the architecture's event queue exists |
| Password breach check | Small embedded common-password blocklist | Add Have I Been Pwned k-anonymity lookup |
| Apple/Facebook login | Real signature/JWKS verification implemented, untested against live providers (no network access to test with in this environment) | Verify against real credentials in a real environment before enabling |

Everything in that table is structured behind a narrow interface specifically so the swap is localized — see each file's docstring.

---

## Configuration

All configuration is environment-driven — see [`.env.example`](.env.example) for the full list with descriptions. A few worth calling out:

- `TOKEN_HASH_PEPPER` / `MFA_ENCRYPTION_KEY` — **must** be changed from the placeholder values before running anywhere but a throwaway sandbox. `scripts/generate_jwt_keys.py` prints ready-to-use values.
- `REQUIRE_EMAIL_VERIFICATION_TO_LOGIN` — defaults to `false`. Per spec section 5.1, unverified accounts may "log in with limited access"; this codebase reflects `email_verified`/`mobile_verified` in the JWT claims for downstream endpoints to gate on, rather than blocking login outright. Flip this to `true` for a stricter policy.
- `GOOGLE_CLIENT_ID` / `APPLE_CLIENT_ID` / `FACEBOOK_APP_ID` + `FACEBOOK_APP_SECRET` — leave unset to disable that social provider (attempts return `SOCIAL_TOKEN_INVALID` with a clear message rather than a crash).

---

## Design notes

A few decisions worth knowing about if you're extending this:

- **Refresh token rotation** creates a new `user_sessions` row on every rotation (linked via `parent_session_id`/`replaced_by_session_id`, sharing a `token_family_id`), matching the schema in the spec exactly. Presenting an already-rotated token is treated as theft: the whole family is revoked and the user's `token_version` is bumped, invalidating every outstanding access token immediately.
- **Password hashing is Argon2id; everything else (refresh tokens, OTPs, recovery codes) is HMAC-SHA256** with a server-side pepper. Argon2's deliberate slowness defends low-entropy, human-chosen secrets; it adds cost with no benefit for already-high-entropy random tokens. See `application/security.py`'s module docstring.
- **The DB session commits even when a request is rejected** (`core/database.py::get_db`), as long as the rejection is an expected `AppError`. This matters: a rejected login still needs to persist the incremented failed-attempt counter and, on the 5th failure, the lockout itself — a blanket rollback-on-any-exception would silently discard that. Only genuinely unexpected exceptions roll back.
- **The transactional outbox** (`event_outbox` table) is written in the same transaction as the business change, then delivered by a background poller — never inline in the request. This guarantees "the notification must not be sent inside the database transaction" from spec section 6.2 while still never losing an event to a crash between the two. The poller starts as soon as the app process does, which can be before migrations have run (e.g. the first couple of seconds of `docker compose up`); it detects that specifically (via the Postgres `42P01`/`undefined_table` error code) and waits quietly rather than logging a stack trace on every tick.
- **The outbox dispatcher is now generic** (`app/core/outbox.py`), shared by both modules' own `event_outbox` tables (Identity's `event_outbox`, Onboarding's `onboarding_event_outbox` — different physical tables, matching each spec's "owned tables" list, but identical polling/locking/retry logic). Each module supplies its own model and a `deliver(row, session)` callback; Onboarding's callback also handles **post-approval activation** — see below.
- **Post-approval Identity/Provider activation happens asynchronously through the outbox, not inline in the approval request** (spec 16.2 explicitly calls for this). `DecisionService.approve()` never calls Identity or Provider directly; it enqueues an event with `postApprovalAction: "ACTIVATE"`, and the outbox dispatcher (`onboarding/application/outbox_dispatcher.py`) performs the actual role transition and provider/institution activation once the approval transaction has safely committed. This is genuinely real, not mocked, for the Identity half — it calls Identity's own `IdentityCommandService.replace_role`/`assign_role`, the exact cross-module contract that service was built for.
- **Maker-checker is enforced server-side, not just via permissions** (spec 16.1). A `BACK_OFFICE_REVIEWER` role doesn't have `ONBOARDING_APPLICATION_APPROVE` at all (blocked at the permission layer), but a `BACK_OFFICE_APPROVER` *does* have both review and approval permissions — so `DecisionService._assert_maker_checker` separately checks that the approver isn't the applicant, wasn't a reviewer, and didn't review any document on this specific application, regardless of what their role permits in general.
- **Claiming an application is race-safe**, not just permission-checked. `AssignmentService.claim` uses `SELECT ... FOR UPDATE` (spec section 28's own example) so two reviewers racing to claim the same application can't both succeed — verified with a real concurrent-request test (`test_concurrent_claims_only_one_succeeds`), not just sequential calls.
- **Three of Onboarding's owned tables aren't given explicit DDL in the spec** (`onboarding_review_checklists`, `onboarding_reverification_cases`, `onboarding_application_notes` — only listed as owned in section 2.2). Each is designed to fit the surrounding spec text and flagged in `domain/models.py`'s docstrings; a fourth deviation (`onboarding_application_sections.data`) stores section field values locally since the spec permits delegating that to a Provider module that doesn't exist yet (section 8.4) — see that column's comment for the reasoning.

---

## Troubleshooting

- **`docker compose up` fails with "in 18+, these Docker images are configured to store database data in a format which is compatible with pg_ctlcluster..."**: this was a real bug in an earlier version of this repo's `docker-compose.yml` — PostgreSQL's official image changed its data directory to a version-specific path starting at major version 18, so the volume must be mounted at the parent `/var/lib/postgresql`, not `/var/lib/postgresql/data`. Already fixed here; if you still hit it, run `docker compose down -v` once (removes the volume created under the old, broken mount point) and `docker compose up --build` again.
- **`citext` / `gen_random_uuid` errors on migrate:** the migration creates the `citext` extension itself; if you're running against a Postgres without the `postgresql-contrib` package (only relevant for bare-metal installs, not Docker), install that package first.
- **`ImportError` / key errors on startup:** you likely skipped `scripts/generate_jwt_keys.py`, or `keys/jwt_private.pem` isn't where `JWT_PRIVATE_KEY_PATH` in `.env` points.
- **Tests fail with "attached to a different loop":** this is a known async-SQLAlchemy + pytest-asyncio interaction; `pyproject.toml` already pins `asyncio_default_fixture_loop_scope = "session"` to avoid it — if you've changed that, revert it.
