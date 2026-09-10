# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Part F: module-scoped whitelisted functions, no raw /api/resource/* exposure.

import frappe

from agency_tracking.contract_parser import parse_contract_file, parse_visa_file
from agency_tracking.state_machine import (
	assert_placement_not_terminal,
	lock_applicant_row,
	strip_lifecycle_fields,
	transition,
)


# The staff who own parsed contract/visa data and may correct it by hand when a parse misses or
# mis-reads a field (Contract Parser is the dedicated role; the usual management fallback too).
PARSE_EDIT_ROLES = {"Contract Parser", "Manager", "Admin", "System Manager"}

# Who may record a medical result (post-Selected and pre-departure): the dedicated Medical Officer
# role plus the existing Placement writers (management + back-office). 2026-09-05.
MEDICAL_RECORD_ROLES = {"Medical Officer", "Manager", "Admin", "System Manager", "Contract Parser", "Ticketer"}

# Only the parsed contract/visa identifier fields are hand-editable here — never lifecycle/status
# fields (those move via transition() only), never the applicant/contractor links. visa_number is
# the one the Injaz paper's left barcode is built from; the rest travel with it.
PARSED_EDITABLE_FIELDS = (
	"visa_number",
	"visa_type",
	"visa_issue_date",
	"visa_expiry_date",
	"visa_reference_number",
	"contract_number",
	"contract_signed_date",
	"employer_name",
	"employer_national_id",
	"employer_address",
	"saudi_agency_name",
	"saudi_agency_license",
	"kuwait_agency_name",
	"kuwait_agency_license",
	"employment_site",
	"contract_duration",
	"contract_salary_amount",
	"contract_salary_currency",
	"sponsor_name",
	"sponsor_civil_id",
)


def _linked_contractor_or_staff_write(placement):
	"""Keyed off an actual linked Contractor record, not role membership — the special
	Administrator user carries every role in the system, so a role-membership check alone
	can't tell "logged in as an agency" from "logged in as staff". Contract Parser is the
	dedicated staff role for this (2026-08-29) -- has_permission already covers it via the
	doctype-level write grant added to Placement."""
	linked_contractor = frappe.db.get_value("Contractor", {"user": frappe.session.user}, "name")
	if linked_contractor:
		if linked_contractor != placement.contractor:
			frappe.throw("Not permitted.", frappe.PermissionError)
	elif not placement.has_permission("write"):
		frappe.throw("Not permitted.", frappe.PermissionError)


@frappe.whitelist()
def upload_contract(placement_name, file_url):
	"""Standard track (Part I Step 4): attach the signed contract to an already-selected
	Placement (created by portal_api.select_candidate in Step 3) and extract contract_signed_date
	plus, per destination_country, the structured fields contract_parser.parse_contract_file
	knows how to pull out (Saudi: contract#/visa#/employer/agency; Kuwait: employer/site/
	duration/salary only -- its template carries far less). Either the contractor who made the
	selection, or internal staff (Contract Parser and the general fallback roles), may upload."""
	placement = frappe.get_doc("Placement", placement_name)
	_linked_contractor_or_staff_write(placement)

	# Parsing is informational only: attach the file + fill parsed data fields, but never let
	# it move the Placement's stage (strip_lifecycle_fields). Stage moves go through
	# advance_placement()/transition() only. See state_machine.LIFECYCLE_FIELDS.
	extracted = strip_lifecycle_fields(parse_contract_file(file_url, placement.destination_country))
	placement.contract_file = file_url
	placement.update(extracted)
	placement.save(ignore_permissions=True)
	return placement.as_dict()


@frappe.whitelist()
def upload_visa(placement_name, file_url):
	"""Kuwait only: a separate document from the contract, uploaded alongside it. Carries
	visa_number/type/dates plus the agency name/license the Kuwait contract itself never has.
	Cross-checks the parsed agency identity against this Placement's actual Contractor and
	flags a mismatch (notify, never auto-reassigns)."""
	placement = frappe.get_doc("Placement", placement_name)
	if placement.destination_country != "Kuwait":
		frappe.throw("Visa upload is only applicable to Kuwait placements.", frappe.ValidationError)
	_linked_contractor_or_staff_write(placement)

	# Informational-only, same as upload_contract: never let parsed data advance the stage.
	extracted = strip_lifecycle_fields(parse_visa_file(file_url))
	placement.visa_file = file_url
	placement.update(extracted)
	placement.save(ignore_permissions=True)

	parsed_agency_name = extracted.get("kuwait_agency_name")
	if parsed_agency_name:
		actual_agency_name = frappe.db.get_value("Contractor", placement.contractor, "contractor_name")
		if actual_agency_name and parsed_agency_name.strip().lower() != actual_agency_name.strip().lower():
			from agency_tracking.notification_engine import notify

			# Manager only -- Admin isn't push-notified for routine alerts (2026-09-05).
			for user in frappe.get_all("Has Role", filters={"role": "Manager"}, pluck="parent"):
				notify(
					user,
					"kuwait_visa_agency_mismatch",
					{
						"placement": placement_name,
						"visa_agency_name": parsed_agency_name,
						"contractor_name": actual_agency_name,
					},
				)

	return placement.as_dict()


@frappe.whitelist()
def create_muayena_placement(applicant_name, contractor_name, file_url=None):
	"""Muayena track (Part A.1 / Part I Step 4): "enters directly at Selected with contract in
	hand" — no portal, no CV. Internal staff (Registrar/Manager/Admin/Contract Parser) only —
	a Muayena candidate is matched to an agency directly, not through the public portal.

	2026-08-29 correction: destination_country is no longer a parameter here. It used to be
	set as a side effect of this call (the old assumption was that Muayena's destination
	becomes known only once a contract names it); that was wrong — it's selected during
	Draft/Registered same as Standard, and is now part of MUAYENA_REGISTERED_REQUIRED_FIELDS.
	The contractor is always picked manually for Muayena (both countries) — Saudi's contract
	*can* carry a labeled agency name/license for cross-checking, but auto-assignment isn't
	attempted at creation time either way; Kuwait's contract never carries one at all.
	"""
	lock_applicant_row(applicant_name)
	applicant = frappe.get_doc("Applicant", applicant_name)
	if not applicant.has_permission("write"):
		frappe.throw("Not permitted.", frappe.PermissionError)

	if applicant.entry_track != "Muayena":
		frappe.throw(
			"Only Muayena-track candidates enter directly via contract upload; "
			"Standard-track candidates go through the portal (Step 3).",
			frappe.ValidationError,
		)
	if applicant.status != "Registered":
		frappe.throw(
			f"{applicant_name} must be Registered before a Placement can be created "
			f"(currently '{applicant.status}').",
			frappe.ValidationError,
		)
	if not applicant.destination_country:
		frappe.throw(f"{applicant_name} has no destination_country set.", frappe.ValidationError)
	current_lock = frappe.db.get_value("Applicant", applicant_name, "active_placement")
	if current_lock:
		frappe.throw(f"{applicant_name} already has an active Placement.", frappe.ValidationError)

	extracted = parse_contract_file(file_url, applicant.destination_country) if file_url else {}
	placement = frappe.get_doc(
		{
			"doctype": "Placement",
			"applicant": applicant_name,
			"contractor": contractor_name,
			"destination_country": applicant.destination_country,
			"status": "Selected",
			"contract_file": file_url,
			**extracted,
		}
	).insert(ignore_permissions=True)

	frappe.db.set_value("Applicant", applicant_name, "active_placement", placement.name)
	return placement.as_dict()


@frappe.whitelist()
def record_selected_medical_result(placement_name, status, examination_date=None, expiry_date=None):
	"""New post-contract medical checkpoint (2026-08-29): gates Selected -> Processing (see
	state_machine.medical_selected_gate). FIT just records the result; UNFIT cancels the whole
	Applicant + Placement via the same cascade as applicant_api.cancel_applicant, uniformly
	for every track/country -- nothing forward from here."""
	if status not in ("FIT", "UNFIT"):
		frappe.throw("status must be 'FIT' or 'UNFIT'.", frappe.ValidationError)
	placement = frappe.get_doc("Placement", placement_name)
	if not (MEDICAL_RECORD_ROLES & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	assert_placement_not_terminal(placement)

	placement.medical_selected_status = status
	placement.medical_selected_examination_date = examination_date
	placement.medical_selected_expiry_date = expiry_date
	placement.save(ignore_permissions=True)

	if status == "UNFIT":
		from agency_tracking.applicant_api import cancel_applicant

		cancel_applicant(placement.applicant, "Medical (Selected stage) result: UNFIT.")

	return placement.as_dict()


@frappe.whitelist()
def record_predeparture_medical_result(placement_name, status, examination_date=None):
	"""Pre-departure medical checkpoint (~72h before flight, Part A.2 Stage 8 / Step 6): gates
	Ticketed -> Departed (see state_machine.medical_2_gate). Mirrors
	record_selected_medical_result's shape -- FIT just records the result and lets
	advance_placement(new_status="Departed") pass the gate; UNFIT cancels the whole Applicant +
	Placement via the same cascade, since a failed pre-departure medical this late (ticket
	already purchased) has no forward path either, same as the earlier Selected-stage check."""
	if status not in ("FIT", "UNFIT"):
		frappe.throw("status must be 'FIT' or 'UNFIT'.", frappe.ValidationError)
	placement = frappe.get_doc("Placement", placement_name)
	if not (MEDICAL_RECORD_ROLES & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	assert_placement_not_terminal(placement)

	placement.medical_2_status = status
	placement.medical_2_examination_date = examination_date
	placement.save(ignore_permissions=True)

	if status == "UNFIT":
		from agency_tracking.applicant_api import cancel_applicant

		cancel_applicant(placement.applicant, "Medical (pre-departure) result: UNFIT.")

	return placement.as_dict()


@frappe.whitelist()
def advance_placement(placement_name=None, new_status=None, override_reason=None, **kwargs):
	"""Move a Placement forward through its lifecycle via the sanctioned transition() path
	(Part C). Passing override_reason attempts a Manager Override if the move is gate-blocked
	(business-workflow-srs.md: "always with a written reason") — transition() itself enforces
	the Manager/Admin role check and that the reason is non-empty.

	This is the direct/manual path -- Processing -> Stamped can also happen on its own via
	state_machine.auto_advance_placement_if_ready() once every mandatory Clearance Step is
	done, so a caller here may find the placement already at new_status by the time they ask
	(idempotent no-op below), not just already-in-that-state from a repeated click.
	"""
	placement_name = placement_name or kwargs.get("placement") or kwargs.get("name")
	new_status = new_status or kwargs.get("status") or kwargs.get("target_status")
	if not placement_name or not new_status:
		frappe.throw("Both placement_name and new_status are required.", frappe.ValidationError)

	if not frappe.db.exists("Placement", placement_name):
		frappe.throw(f"Placement {placement_name} not found.", frappe.DoesNotExistError)
	placement = frappe.get_doc("Placement", placement_name)
	# S-1 (2026-09-05): lifecycle advance is management, OR the officer actually assigned to THIS
	# placement's current stage (holds an open ToDo on it) -- not every role that happens to have
	# Placement write (which included Ticketer/Contract Parser, letting them advance any placement's
	# whole lifecycle). The gates still enforce the stage conditions on top of this.
	from agency_tracking.finance_engine import is_assigned_to_placement

	if not (
		frappe.session.user == "Administrator"
		or ({"Manager", "Admin", "System Manager"} & set(frappe.get_roles()))
		or is_assigned_to_placement(frappe.session.user, placement_name)
	):
		frappe.throw("Not permitted.", frappe.PermissionError)

	if placement.status == new_status:
		return placement.as_dict()

	return transition(
		placement, new_status, override=bool(override_reason), override_reason=override_reason
	).as_dict()


@frappe.whitelist()
def record_ticket_details(placement_name, ticket_number, flight_date, ticket_cost=None, currency=None):
	"""Ticketer role. ticket_cost (if given) auto-logs a Pending Applicant Transaction expense
	-- same pattern as clearance-step payments, everything money-related feeds the one Finance
	ledger.

	2026-08-30 fix (backend-issues #05): ticket_number/flight_date are pure logistics fields with
	no FX dependency -- the cost-logging sub-step now runs inside its own DB savepoint, so a
	missing FX rate for `currency` only unwinds the failed expense insert, not the ticket fields
	saved just above (which is the doc.save() call still pending in the same transaction, same
	as it always was -- only the failure boundary changed). The cost log is best-effort from
	here on: failure is reported back to the caller as a warning, not a fatal error for the
	whole call."""
	placement = frappe.get_doc("Placement", placement_name)
	if not placement.has_permission("write"):
		frappe.throw("Not permitted.", frappe.PermissionError)
	assert_placement_not_terminal(placement)

	placement.ticket_number = ticket_number
	placement.flight_date = flight_date
	placement.ticket_cost = ticket_cost
	placement.save(ignore_permissions=True)

	result = placement.as_dict()
	if ticket_cost:
		from agency_tracking.finance_api import _log_stage_transaction

		save_point = frappe.generate_hash(length=10)
		frappe.db.savepoint(save_point)
		try:
			_log_stage_transaction(
				"Expense", ticket_cost, currency or "ETB", f"Ticket cost for {placement_name}", placement_name, None
			)
		except Exception:
			frappe.db.rollback(save_point=save_point)
			frappe.log_error(
				title="Ticket cost logging failed",
				message=f"{placement_name}: {frappe.get_traceback()}",
			)
			result["warning"] = (
				f"Ticket saved, but the cost wasn't logged — ask Finance to set an FX rate for "
				f"{currency or 'ETB'} (finance_api.set_fx_rate), then log it manually via "
				f"finance_api.log_stage_expense."
			)
	return result


@frappe.whitelist()
def record_reschedule(placement_name, reschedule_date, reschedule_cause, reschedule_cost=None, currency=None):
	"""Ticketer role. reschedule_cost is only meaningful/loggable when cause is Internal --
	an airline/airport-caused reschedule isn't billed to us."""
	if reschedule_cause not in ("Internal", "Airport"):
		frappe.throw("reschedule_cause must be 'Internal' or 'Airport'.", frappe.ValidationError)
	placement = frappe.get_doc("Placement", placement_name)
	if not placement.has_permission("write"):
		frappe.throw("Not permitted.", frappe.PermissionError)
	assert_placement_not_terminal(placement)

	placement.is_rescheduled = 1
	placement.reschedule_date = reschedule_date
	placement.reschedule_cause = reschedule_cause
	placement.reschedule_cost = reschedule_cost if reschedule_cause == "Internal" else None
	placement.save(ignore_permissions=True)

	if reschedule_cause == "Internal" and reschedule_cost:
		from agency_tracking.finance_api import _log_stage_transaction

		_log_stage_transaction(
			"Expense",
			reschedule_cost,
			currency or "ETB",
			f"Internal reschedule cost for {placement_name}",
			placement_name,
			None,
		)
	return placement.as_dict()


@frappe.whitelist()
def list_placements(filters=None, limit_page_length=100, order_by="modified desc"):
	"""backend-issues #02: the whitelisted list surface Placement never had -- callers used to
	fall back to raw /api/resource/Placement, which only Manager/Admin/System Manager/Contract
	Parser/Ticketer could read (Placement's doctype-level permissions), 403ing every other role
	that legitimately needs to resolve a placement reference (Finance Manager, Clearance Officer,
	Complaint Manager, Communication Manager, the six country+step roles -- all granted read-only
	access on the doctype itself, see placement.json). frappe.get_list enforces those permissions
	the same way it would for any other doctype; no separate role check needed here."""
	if isinstance(filters, str):
		filters = frappe.parse_json(filters)
	return frappe.get_list(
		"Placement",
		filters=filters,
		fields=["*"],
		limit_page_length=frappe.utils.cint(limit_page_length) or 100,
		order_by=order_by,
	)


@frappe.whitelist()
def update_placement_parsed_fields(placement_name=None, **data):
	"""Hand-edit the parsed contract/visa identifiers on a Placement — primarily the visa number
	(the Injaz paper's left barcode) when parsing missed it or read it wrong.

	Restricted to the parsing staff (Contract Parser + the management fallback); Foreign Agency
	users can never reach it. Only PARSED_EDITABLE_FIELDS are accepted — status/applicant/contractor
	and every other lifecycle field are ignored, so this can neither move a placement's stage nor
	reassign it. In the Desk these fields are already editable directly by Contract Parser; this is
	the headless equivalent (Part F: no raw /api/resource writes)."""
	placement_name = placement_name or data.pop("name", None) or data.pop("placement", None)
	if not placement_name:
		frappe.throw("placement_name is required.", frappe.ValidationError)
	if frappe.session.user != "Administrator" and not (PARSE_EDIT_ROLES & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)

	placement = frappe.get_doc("Placement", placement_name)
	assert_placement_not_terminal(placement)

	updates = {k: v for k, v in data.items() if k in PARSED_EDITABLE_FIELDS}
	if not updates:
		frappe.throw(
			"No editable field supplied. Allowed: " + ", ".join(PARSED_EDITABLE_FIELDS),
			frappe.ValidationError,
		)
	placement.update(updates)
	placement.save(ignore_permissions=True)
	return placement.as_dict()


@frappe.whitelist()
def get_placement(placement_name=None, **kwargs):
	placement_name = placement_name or kwargs.get("name") or kwargs.get("placement")
	if not placement_name:
		frappe.throw("placement_name is required.", frappe.ValidationError)
	if not frappe.db.exists("Placement", placement_name):
		frappe.throw(f"Placement {placement_name} not found.", frappe.DoesNotExistError)
	doc = frappe.get_doc("Placement", placement_name)
	if not doc.has_permission("read"):
		frappe.throw("Not permitted.", frappe.PermissionError)
	return doc.as_dict()
