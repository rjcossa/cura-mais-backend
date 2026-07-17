# Health Platform & Digital Medicine Marketplace

An integrated digital health platform connecting patients with healthcare professionals, hospitals, nutritionists, and pharmacies — supporting service discovery, consultations, e-prescriptions, medicine ordering, nutrition planning, health education, and digital payments.

## Overview

The platform provides secure, role-based experiences across web and mobile for the following stakeholders:

- **Patients** — discover providers, book consultations, complete screenings, receive prescriptions, purchase medicines, follow nutrition plans, attend webinars.
- **Doctors** — manage professional profiles, availability, and fees; conduct consultations; issue e-prescriptions and referrals; host webinars.
- **Nutritionists** — manage profiles and availability; run assessments; build and track personalised nutrition plans.
- **Hospitals & Clinics** — register institutions, manage affiliated professionals, departments, and bookings; run campaigns and access reporting.
- **Pharmacies** — manage branches and inventory, review and fulfil prescriptions, handle orders, collection, and delivery.
- **Back-Office Administrators** — verify and approve providers/institutions, manage disputes and complaints, oversee content, promotions, and platform reporting.

## Core Capabilities

- Discovery and booking of healthcare services (search, filters, ratings/reviews)
- Preliminary patient screening and health assessments, with emergency-symptom safeguards
- Online (video/audio/text) and in-person consultations, with anti-double-booking controls
- Electronic prescriptions, plus review of externally issued/uploaded prescriptions
- Pharmacy & medicine marketplace: inventory, ordering, prescription review, collection/delivery
- Nutrition planning: assessments, meal plans, progress tracking
- Pro-bono consultations with abuse-prevention controls
- Webinars and health education content
- Digital payments: consultations, medicines, webinars, nutrition programmes, commissions, settlements, and refunds
- Promotions and advertising, subject to review and medical-content restrictions
- Notifications across in-app, email, SMS, push, and (where applicable) WhatsApp
- Ratings, reviews, and complaint/dispute resolution workflows
- Admin dashboards and exportable reporting
- Data privacy & consent controls, purpose-based access, and audit trails
- Role-based access control, MFA, encryption, and other security controls

See [`docs/requirements.md`](docs/requirements.md) for the full high-level business requirements document, including verification/approval workflows, registration data requirements, medical records handling, delivery management, and future-release scope (laboratories, insurance/corporate health, etc.).

## Getting Started

Two modules are implemented and ready to run — see [`backend/README.md`](backend/README.md) for full setup instructions:

- **Identity** — registration, authentication, sessions, MFA, social login, roles/permissions.
- **Onboarding** — applicant onboarding, document review, verification checks, and maker-checker approval for doctors, nutritionists, hospitals, clinics, and pharmacies.

Quick version, with Docker:

```bash
cd backend
cp .env.example .env
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python scripts/generate_jwt_keys.py   # paste printed values into .env
docker compose up --build
docker compose exec app alembic upgrade head
docker compose exec app python -m scripts.seed_roles_permissions
docker compose exec app python -m scripts.seed_document_requirements
```

API docs: <http://localhost:8000/docs> · Static OpenAPI spec: [`backend/openapi/api.yaml`](backend/openapi/api.yaml)

Other modules (Provider Directory, Scheduling, Pharmacy, ...) aren't built yet — `backend/README.md`'s [Project layout](backend/README.md#project-layout) section explains where each one plugs into the same modular-monolith backend as it's added.

## Suggested Product Modules

1. Identity, registration, and authentication
2. Professional and institution onboarding
3. Back-office verification
4. Provider directory and search
5. Screening and health assessments
6. Appointment and calendar management
7. Virtual consultation
8. Electronic prescriptions
9. Pharmacy marketplace
10. Medicine inventory and order fulfilment
11. Nutrition planning
12. Webinars and health content
13. Payments, commissions, and settlements
14. Promotions and advertising
15. Notifications and communication
16. Ratings, complaints, and disputes
17. Patient health records
18. Administration and reporting
19. Security, privacy, consent, and audit
20. Integration and API management

## MVP Scope

The first release focuses on core value proposition:

- Patient, doctor/nutritionist, and pharmacy registration
- Back-office verification and approval
- Search for doctors, nutritionists, pharmacies, and medicines
- Provider profiles and appointment booking
- Video consultation integration
- Preliminary screening questionnaires
- Consultation payments
- Electronic prescription issuance and upload
- Pharmacy inventory management and medicine ordering (with prescription review, collection only)
- Basic nutrition plan creation
- Notifications
- Basic administration and reporting
- Audit trails, consent, privacy, and security controls

**Deferred to later releases:** medicine delivery, hospital management functionality, insurance integration, laboratory integration, advanced patient health records, corporate health programmes, automated screening support, AI-enabled clinical decision support, advanced promotions, subscriptions/membership, wearable integration, multilingual content, loyalty programmes.

## Key Business Decisions Pending

Several decisions need confirmation before/during development — see Section 25 of the [requirements document](docs/requirements.md), including operating jurisdiction(s) and applicable regulation, the platform's legal role (intermediary vs. active provider), payment/settlement/commission model, medicine delivery policy, and data residency for patient records.

## Repository Structure

```
.
├── README.md
├── docs/
│   └── requirements.md      # Full high-level business requirements
└── backend/                 # Application backend (modular monolith)
    ├── README.md             # Setup, testing, and design notes
    ├── app/
    │   ├── core/              # Cross-cutting: config, DB, error handling, rate limiting, notifications
    │   ├── shared/             # Port interfaces + mocks for not-yet-built dependencies (Documents, Provider, Institution)
    │   └── modules/
    │       ├── identity/        # Registration, auth, sessions, MFA, social login, roles
    │       └── onboarding/      # Applicant onboarding, review, verification, maker-checker approval
    ├── alembic/               # Database migrations
    ├── scripts/               # Key generation, seeding, OpenAPI export
    ├── tests/                 # 112 tests, run against a real PostgreSQL database
    ├── openapi/               # Exported OpenAPI/Swagger spec (api.yaml/.json)
    └── docker-compose.yml     # Postgres + app + Adminer for local development
```

## Status

🚧 Active development. The **Identity** and **Onboarding** module backends are implemented, tested, and runnable (see [Getting Started](#getting-started)). Remaining modules from the [suggested product modules](#suggested-product-modules) list above are not yet built.

## License

TBD.
