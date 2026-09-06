# API Inventory (grouped by role) + Useful Native Frappe Endpoints

119 whitelisted functions across 20 files, grouped by who's meant to use them. Roles are
additive: most endpoints are `{specific role} ∪ Manager ∪ Admin ∪ System Manager`, since
Manager/Admin sit on top of almost everything.

## Foreign Agency (external, portal-only — `desk_access=0`)
- `create_agency_thread`, `send_message`, `list_threads`, `get_thread_messages`, `mark_read` — chat with their Communication Manager
- `create_complaint` — file a complaint (own placements only)
- `list_portal_candidates`, `get_candidate_detail`, `get_candidate_photo` — browse the recruitment marketplace (own destination country only)
- `select_candidate` — reserve a candidate into a Placement (row-locked, idempotent)
- `list_my_placements`, `list_my_wakala_requests` — their own tenant-scoped views
- `upload_contract`, `upload_visa` — attach signed docs to their own placement

## Registrar
- Applicant creation (via doctype permissions, not a whitelisted API — the CRUD happens through standard Frappe doc save)
- `create_contractor`, `list_contractors`, `get_commission_rates`, `set_commission_rates` (shares `CONTRACTOR_MANAGE_ROLES` with Manager/Finance Manager/Communication Manager)
- `generate_cv`, `render_cv_pdf`

## Clearance Officer (+ six country-step roles: Saudi/Kuwait LMIS, Taeshir/Telesign, Embassy)
- `assign_clearance_step`, `complete_clearance_step`, `start_clearance_step`
- `submit_embassy_step`, `stamp_embassy_step`, `reject_embassy_step`
- `set_taeshir_appointment`, `reschedule_taeshir_appointment`, `record_injaz_payment`, `forfeit_injaz_and_restart`, `render_injaz_pdf`
- `list_my_clearance_steps` / `list_assigned_steps` (their queue)
- Country-role gating happens per-step via `CLEARANCE_ROLE_BY_STEP_TYPE` — e.g. only "Saudi LMIS" holders can act on an LMIS step for Saudi, not a generic Clearance Officer

## Ticketer
- `record_ticket_details`, `record_reschedule`
- `advance_placement` (if assigned via ToDo)
- Also included in `MEDICAL_RECORD_ROLES`, so can record medical results too

## Medical Officer
- `record_selected_medical_result`, `record_predeparture_medical_result` (shared with Ticketer/Contract Parser/Manager/Admin)

## Contract Parser
- `update_placement_parsed_fields` (hand-correct parsed contract/visa fields)
- Shares `parse_contract_file`/`parse_visa_file` (these actually have **no role check at all** — see flag below) and medical-result recording

## Complaint Manager
- `list_unresolved_complaints`, `list_new_complaints`, `list_complaints`, `acknowledge_complaint`, `resolve_complaint`

## Finance Manager
- `log_stage_expense`/`log_stage_income` (shared with all internal staff), `approve_transaction`, `reject_transaction`, `void_transaction`
- FX: `get_fx_rate`, `set_fx_rate`, `fetch_fx_rates_now`
- Commissions: `get_owed_commissions(_by_currency)`, `create_commission_batch`, `write_off_batch`, `record_batch_advance`, `release_unpaid_items`, `list_commission_batches`, `get_commission_batch`, `settle_batch` (+ four-eyes rule over 100,000 ETB), `settle_batch_items`, `upload_batch_payment_proof`, `get_batch_invoice_pdf`
- Reconciliation: `upload_bank_statement`, `manually_match_line`
- Also sits in `MANAGEMENT_ROLES`, so gets all the reports below too

## Communication Manager
- `create_agency_thread` (on an agency's behalf), `create_internal_thread`, `add_participant`
- `list_all_threads`, `get_thread_messages` (oversight — sees every thread, not just own)
- Contractor management endpoints (shared)

## Manager / Admin / System Manager (management tier — broadest access)
- Everything above, plus:
- **Reports** (`report_api.py`): `get_daily_work_report`, `get_staff_performance_report`, `get_complaint_aging_report`, `get_financial_overview`, `get_pending_approval_queue`, `get_cost_breakdown_report`, `get_employee_financial_report`, `get_placement_aging_report`, `get_operations_summary`, `export_commissions_xlsx`
- **Employee admin** (`employee_api.py`, Admin/Manager/System Manager only): `list_employees`, `create_employee`, `update_employee_roles`, `reset_employee_password`, `toggle_employee_status`, `delete_employee`
- `get_assignable_roles`, `reassign_clearance_step`, `trigger_early_commission_accrual`
- `advance_placement` unconditionally (bypasses the ToDo-assignment check)
- Storage/notification infra: `test_storage_connection`, `regenerate_vapid_keys` (System Manager/Administrator only)

---

## ⚠️ Worth a look before building on top of these

- **No explicit role check at all**: `get_corridor_steps`, `list_my_clearance_steps`/`list_assigned_steps`, `parse_contract_file`, `parse_visa_file`, `list_placements` (relies entirely on `frappe.get_list`'s implicit doctype permission — no custom gate). Not necessarily bugs, but worth confirming each is intentionally open to any authenticated user.
- **Docstring/implementation mismatch**: `report_api.get_financial_overview` is commented "Admin-only" but its actual `_require_admin()` allows Admin + System Manager + Finance Manager + Manager.
- **Duplicate/shadowed `MANAGEMENT_ROLES`**: `report_api.py` defines its own module-level `MANAGEMENT_ROLES = {Manager, Admin, Finance Manager, System Manager}`, and then `get_placement_aging_report()` locally redefines an even narrower `MANAGEMENT_ROLES = {Manager, Admin}` that shadows it — so that one report excludes Finance Manager/System Manager while every other report in the same file includes them. Looks like an accidental copy-paste rather than intentional.
- At least 4 different files each hand-roll their own local role-set constant (`CONTRACTOR_MANAGE_ROLES`, `STAFF_ADMIN_ROLES`, `PARSE_EDIT_ROLES`, `MEDICAL_RECORD_ROLES`) instead of composing from `roles.py`'s `INTERNAL_STAFF_ROLES`/`MANAGEMENT_ROLES` — not wrong, but it's how the `report_api.py` shadowing bug happened.

---

## Native Frappe endpoints available for free (not custom-built here)

These ship with every Frappe site and are already callable at `/api/method/...` — worth knowing
about before writing bespoke equivalents, especially given the ToDo-based assignment mechanism
already in use.

| Endpoint | What it gives you |
|---|---|
| **`frappe.desk.form.assign_to.add` / `.remove` / `.get` / `.close_all`** | The *real* Frappe assignment API — supports priority, due date, description, and "notify by email." `clearance_engine.py` creates ToDo docs by hand instead of using this; switching would give due-date reminders and the standard Desk "Assigned To" sidebar for free. |
| **`frappe.desk.notifications.get_notifications`** | Aggregated open-count per doctype (the little bell/badge numbers) — could back a "you have N pending clearance steps" indicator without a custom query. |
| **`frappe.client.get_list` / `get_value` / `get_count` / `set_value` / `insert` / `delete`** | Generic CRUD respecting doctype permissions automatically. Useful as a fallback for simple admin screens instead of writing a bespoke `list_x`/`get_x` wrapper for every doctype (~15 of these already written by hand). |
| **`frappe.desk.reportview.get`** | Powers Frappe's List View/Report Builder — filters, sorting, group-by, permission-aware, no code needed. Good for ad hoc internal tables (e.g. "all transactions this month") without adding another `report_api.py` function each time. |
| **`frappe.client.get_list` on `"Comment"` / doc timeline (`_comments`)** | Built-in threaded comments + activity feed on any doc — could be a lighter-weight alternative to parts of the custom chat/timeline for *internal* (non-agency) discussion on a Placement or Applicant. |
| **`frappe.core.doctype.user.user.generate_keys`** | Issues API key/secret pairs per user for token-based (non-session) auth — useful if the frontend or a script needs to call the API without cookie-based login. |
| **`frappe.client.attach_file`** | Generic file-upload-and-attach to any doc — though `storage_engine.py` (R2-backed) is likely intentionally custom here, so probably skip. |
| **`/api/method/login`, `frappe.auth.get_logged_user`** | Standard session login/logout — `auth_api.py` already layers CSRF/role/contractor context on top of this, so this one's already covered. |

The `assign_to` API is the one worth flagging hardest — `is_assigned_to_placement()` and the
ToDo-broadcast mechanism in `clearance_engine.py` reinvent something Frappe already ships with,
with due dates and priority built in.
