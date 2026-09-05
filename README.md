# Agency Tracking

An overseas-recruitment processing platform for labor-sending agencies, built as a
[Frappe](https://frappeframework.com) application. It manages the full applicant lifecycle from
intake to departure across the Ethiopia → Saudi Arabia and Ethiopia → Kuwait corridors, including
document parsing, clearance workflows, commission accounting, and multi-tenant agency portals.

## Overview

The platform models the real recruitment process end to end:

- **Applicant intake** — Standard (portal-selected) and Muayena (contract-in-hand) tracks, with a
  per-stage required-field floor and passport MRZ auto-fill.
- **Document processing** — passport (ICAO 9303 MRZ + checksum validation), contract, visa, and
  Injaz paper parsing, with low-confidence extractions flagged for manual review.
- **Clearance workflow** — data-driven corridor definitions (LMIS, Taeshir/Injaz, Embassy, Telesign)
  with role-based officer routing, appointment and Injaz-payment tracking, and generated Injaz PDFs.
- **Placement lifecycle** — a strict state machine (`Selected → Processing → Stamped → Ticketed →
  Departed`) with gated transitions, manager overrides, and an append-only audit trail.
- **Finance** — multi-currency commissions normalized to a base currency via cached FX rates,
  batch settlement with partial payment, advances, write-offs, and carry-over of unpaid items.
- **Agency portal** — tenant-isolated candidate discovery, selection, and messaging for foreign
  agencies.
- **Notifications** — web push and WhatsApp delivery for assignments, reminders, and watchdog
  alerts (medical expiry, contract age, appointment/payment reminders, departure follow-up).

## Architecture

The codebase separates concerns cleanly:

| Layer | Responsibility |
|-------|----------------|
| `*_api.py` | Whitelisted HTTP endpoints and permission checks |
| `*_engine.py`, `state_machine.py` | Business logic and the transition state machine |
| `agency_tracking/doctype/**` | Data model and record-level validation |

All state changes flow through a single `transition()` path, and every write surface is a
module-scoped whitelisted method — there is no raw `/api/resource` access to any doctype.

## Tech stack

- Frappe Framework (Python 3.10+, MariaDB, Redis)
- Document parsing: PyMuPDF / pypdf, PassportEye, pytesseract
- Web Push (VAPID) and WhatsApp Cloud API for notifications

## Installation

Requires an existing [Frappe bench](https://frappeframework.com/docs/user/en/installation).

```bash
# from your bench directory
bench get-app https://github.com/hdv438/travel_agency.git
bench --site your-site.local install-app agency_tracking
bench --site your-site.local migrate
```

## Configuration

After installation, configure the following via the Desk:

- **FX Rate Settings** — automatic (public FX source) or manual base-currency rates.
- **Notification Config** — VAPID keys (auto-provisioned on first use) and WhatsApp Cloud API
  credentials.
- **Storage Settings** — optional S3/R2 offload for uploaded documents and receipts.
- **Corridor Definitions** — the ordered clearance steps per destination country (seeded on install
  for Saudi Arabia and Kuwait).

## API

The complete HTTP API is documented in machine-readable form:

- `openapi.yaml` — OpenAPI 3 specification
- `swagger.json` — Swagger 2.0 specification
- `postman_collection.json` / `postman_environment.json` — Postman collection and environment

Every endpoint is reached via `POST /api/method/agency_tracking.<module>.<method>` using a Frappe
session cookie (with CSRF token) or an API token.

## License

MIT — see [license.txt](license.txt).
