# API tests (VS Code REST Client)

`.http` request collections for every endpoint in this service, meant to be run
with the [REST Client](https://marketplace.visualstudio.com/items?itemName=humao.rest-client)
VS Code extension (`humao.rest-client`). Open any `.http` file and click
**Send Request** above a block, or use `Cmd+Alt+R` / `Ctrl+Alt+R`.

## Setup

1. Start the API (from `backend/`):
   ```
   make run          # or: .venv/bin/uvicorn app.main:app --reload
   ```
   It listens on `http://localhost:8000` by default.
2. `EMAIL_PROVIDER` and `SMS_PROVIDER` default to `mock` — verification
   tokens / OTP codes aren't actually emailed or texted, they're **printed to
   the uvicorn console** (see `app/core/notifications.py`). Watch that
   terminal and copy the code into the relevant request when a flow needs
   one (email verification, mobile OTP, password reset).
3. Each file starts with an `@baseUrl` variable — edit it if your server
   runs somewhere other than `localhost:8000`.

## Files

| File | Covers |
|---|---|
| [`system.http`](system.http) | Liveness / readiness checks — no auth |
| [`auth.http`](auth.http) | Registration, login/refresh/logout, email + mobile verification, password, MFA, sessions, social login |
| [`users.http`](users.http) | Current-user profile/email/mobile/deactivation + back-office user administration (roles, suspend/activate) |
| [`onboarding-applicant.http`](onboarding-applicant.http) | The applicant-facing onboarding flow: start application, fill sections, upload documents, submit, respond to info requests |
| [`onboarding-back-office.http`](onboarding-back-office.http) | The reviewer/approver flow: search applications, assign/claim, checklist, verification checks, risk flags, decisions |
| [`providers-self-service.http`](providers-self-service.http) | Provider profile, completeness, registrations, qualifications, specialities, languages, services, locations, affiliations, media, publication, and public profile lookup |
| [`providers-back-office.http`](providers-back-office.http) | Search, detail, corrections, suspend/reinstate/hide, and the institution affiliation confirm/reject stand-in |

## Chaining requests

Requests use REST Client's named-request variables, e.g.:

```http
# @name login
POST {{apiPrefix}}/auth/login
...

###

@accessToken = {{login.response.body.$.data.accessToken}}
```

so once you send the `login` request in a file, `{{accessToken}}` is
available to every request below it **in that same file**. Run requests
top-to-bottom within a file the first time through.

## Two things you'll need to do manually

- **Registration is one-shot.** `POST /auth/register/*` requires a unique
  email/mobile number. The example values will 409 on a second run — either
  edit them or reset your local database before re-running the register
  requests. Every other flow (login, etc.) reuses whatever account already
  exists, so this only matters the first time.
- **Back-office / admin roles have no self-serve bootstrap.** There's no API
  to grant yourself `PLATFORM_ADMIN`, `BACK_OFFICE_REVIEWER`, or
  `BACK_OFFICE_APPROVER` — by design. From `backend/`, create a ready-to-use
  admin account with:
  ```
  python -m scripts.create_user --email admin@example.com --role PLATFORM_ADMIN
  ```
  (password is auto-generated and printed if you don't pass `--password`).
  Use that account's credentials in the `@reviewerEmail`/`@adminEmail`
  variables in [`users.http`](users.http) and
  [`onboarding-back-office.http`](onboarding-back-office.http). For an
  *existing* account, grant a role instead with
  `python -m scripts.assign_role --email you@example.com --role BACK_OFFICE_REVIEWER`.
  Once you have one admin account, you can also use
  [`users.http`](users.http)'s "Assign a role to a user" request to grant
  roles to other accounts through the API itself.
- **MFA codes.** `POST /auth/mfa/authenticator/enrol` returns a TOTP
  `secret`. Compute the 6-digit code from it yourself before calling
  `confirm`/`verify`, e.g.:
  ```
  python3 -c "import pyotp; print(pyotp.TOTP('PASTE_SECRET_HERE').now())"
  ```
