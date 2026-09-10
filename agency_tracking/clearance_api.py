# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Part F: module-scoped whitelisted functions, no raw /api/resource/* exposure.

import frappe
from frappe.utils import formatdate, today

from agency_tracking.clearance_engine import assign_clearance_step as _engine_assign_clearance_step
from agency_tracking.agency_tracking.doctype.clearance_step.clearance_step import CLEARANCE_ROLE_BY_STEP_TYPE
from agency_tracking.pdf_utils import asset_datauri, code128_b_datauri, embed_image_datauri, render_pdf
from agency_tracking.roles import INTERNAL_STAFF_ROLES
from agency_tracking.state_machine import assert_clearance_step_not_terminal, log_action

INJAZ_TEMPLATE = "templates/injaz_document.html"
# The sending (Ethiopian) agency named at the top of the Injaz application header, and the contact
# email printed under the embassy block -- the same identity the Injaz parser recognises as
# origin_agency (ANWAR SULTAN FOREIGN EMPLOYMENT AGENT).
ORIGIN_AGENCY_FULL = "ANWAR SULTAN FOREIGN EMPLOYMENT AGENT"
ORIGIN_AGENCY_EMAIL = "rawnasultan03@gmail.com"
# Applicant.religion -> the wording the Saudi consular form uses.
_RELIGION_MAP = {"Muslim": "Islam"}


@frappe.whitelist()
def assign_clearance_step(clearance_step_name=None, user=None, step_name=None, assigned_to=None, **kwargs):
	"""Assign or reassign a clearance step to an officer."""
	if not ({"Manager", "Admin", "Clearance Officer", "System Manager"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	clearance_step_name = clearance_step_name or step_name or kwargs.get("name")
	user = user or assigned_to or kwargs.get("user")
	if not clearance_step_name or not user:
		frappe.throw("Both clearance_step_name and user are required.", frappe.ValidationError)
	_engine_assign_clearance_step(clearance_step_name, user)
	return {"status": "success", "clearance_step": clearance_step_name, "assigned_to": user}


# LMIS (both countries) completes to "Issued" -- everything else that uses the plain
# complete_clearance_step() path (Taeshir, Telesign) uses the generic "Complete". Embassy
# (Saudi + Kuwait) does NOT go through this function at all -- its Pending -> Submitted ->
# Stamped/Rejected flow needs its own functions below (a remark is required for Rejected,
# and "Stamped" isn't just "the step finished", it's a specific outcome distinct from failure).
TERMINAL_STATUS_BY_STEP_TYPE = {
	"LMIS Clearance": "Issued",
	"Kuwait LMIS": "Issued",
}
DEFAULT_TERMINAL_STATUS = "Complete"


def _is_assigned_officer(clearance_step_name):
	return bool(
		frappe.db.exists(
			"ToDo",
			{
				"reference_type": "Clearance Step",
				"reference_name": clearance_step_name,
				"allocated_to": frappe.session.user,
				"status": "Open",
			},
		)
	)


def _can_act_on_step(step):
	"""Manager/Admin/System Manager always; the officer currently ToDo-assigned to this exact row;
	or anyone holding the role mapped to this step_type."""
	if {"Manager", "Admin", "System Manager"} & set(frappe.get_roles()):
		return True
	if _is_assigned_officer(step.name):
		return True
	required_role = CLEARANCE_ROLE_BY_STEP_TYPE.get(step.step_type)
	return bool(required_role and required_role in frappe.get_roles())


def _close_open_todos(clearance_step_name):
	open_todos = frappe.get_all(
		"ToDo",
		filters={"reference_type": "Clearance Step", "reference_name": clearance_step_name, "status": "Open"},
		pluck="name",
	)
	for todo_name in open_todos:
		frappe.db.set_value("ToDo", todo_name, "status", "Closed")


@frappe.whitelist()
def complete_clearance_step(
	clearance_step_name=None,
	step_name=None,
	name=None,
	reference_no=None,
	amount=None,
	**kwargs,
):
	"""Mark a Clearance Step complete/Issued. Not for Embassy steps -- use
	submit_embassy_step/stamp_embassy_step/reject_embassy_step instead."""
	clearance_step_name = clearance_step_name or step_name or name or kwargs.get("clearance_step")
	if not clearance_step_name:
		frappe.throw("clearance_step_name is required.", frappe.ValidationError)

	step = frappe.get_doc("Clearance Step", clearance_step_name)
	if step.step_type in ("Embassy", "Kuwait Embassy"):
		frappe.throw(
			"Embassy steps use submit_embassy_step/stamp_embassy_step/reject_embassy_step, not complete_clearance_step.",
			frappe.ValidationError,
		)
	if not _can_act_on_step(step):
		frappe.throw("Not permitted.", frappe.PermissionError)
	assert_clearance_step_not_terminal(step)

	step.status = TERMINAL_STATUS_BY_STEP_TYPE.get(step.step_type, DEFAULT_TERMINAL_STATUS)
	step.date_completed = today()
	step.completed_by = frappe.session.user
	if reference_no:
		step.reference_no = reference_no
	if amount is not None:
		step.amount = amount
		step.payment_status = "Paid"
	step.save(ignore_permissions=True)
	_close_open_todos(clearance_step_name)
	return step.as_dict()


def _load_actionable_step(clearance_step_name, expected_types=None):
	"""Load the EXACT Clearance Step to act on -- never guess another placement's step. A missing or
	stale/invalid id is a hard error (2026-09-05 data-integrity fix): the previous behavior silently
	fell back to "the most recently created active step of this type" ACROSS ALL PLACEMENTS, so a
	stale id from the UI would land the action on a different worker's placement -- producing e.g. a
	Departed placement whose own LMIS step is still Pending. Also refuses to edit any step once its
	placement is Departed/Cancelled (that history is final)."""
	if not clearance_step_name:
		frappe.throw("clearance_step_name is required.", frappe.ValidationError)
	if not frappe.db.exists("Clearance Step", clearance_step_name):
		frappe.throw(f"Clearance Step {clearance_step_name} not found.", frappe.DoesNotExistError)
	step = frappe.get_doc("Clearance Step", clearance_step_name)
	if expected_types and step.step_type not in expected_types:
		frappe.throw(
			f"{clearance_step_name} is a '{step.step_type}' step, not one of {sorted(expected_types)}.",
			frappe.ValidationError,
		)
	placement_status = frappe.db.get_value("Placement", step.placement, "status")
	if placement_status in ("Departed", "Cancelled"):
		frappe.throw(
			f"{step.placement} is already {placement_status}; its clearance steps can no longer be edited.",
			frappe.ValidationError,
		)
	return step


@frappe.whitelist()
def start_clearance_step(clearance_step_name=None, step_name=None, name=None, **kwargs):
	clearance_step_name = clearance_step_name or step_name or name or kwargs.get("clearance_step")
	step = _load_actionable_step(clearance_step_name)
	if not _can_act_on_step(step):
		frappe.throw("Not permitted.", frappe.PermissionError)
	if step.status == "In Progress":
		return step.as_dict()
	# S-2: only a not-yet-started step can be started (never revert a Submitted/Complete/etc. step).
	if step.status != "Pending":
		frappe.throw(f"A '{step.status}' clearance step cannot be (re)started.", frappe.ValidationError)
	step.status = "In Progress"
	step.date_started = today()
	step.save(ignore_permissions=True)
	return step.as_dict()


@frappe.whitelist()
def submit_embassy_step(clearance_step_name=None, **kwargs):
	"""Documents submitted (Monday). Saudi/Kuwait Embassy only."""
	clearance_step_name = clearance_step_name or kwargs.get("name") or kwargs.get("clearance_step")
	step = _load_actionable_step(clearance_step_name, {"Embassy", "Kuwait Embassy", "Saudi Embassy"})
	if not _can_act_on_step(step):
		frappe.throw("Not permitted.", frappe.PermissionError)
	if step.status == "Submitted":
		return step.as_dict()
	# S-2: submit only from a pre-submit state (not from an already-Stamped/Rejected step).
	if step.status not in ("Pending", "In Progress"):
		frappe.throw(f"An embassy step that is '{step.status}' cannot be submitted.", frappe.ValidationError)
	step.status = "Submitted"
	step.date_started = today()
	step.save(ignore_permissions=True)
	return step.as_dict()


@frappe.whitelist()
def stamp_embassy_step(clearance_step_name=None, reference_no=None, **kwargs):
	"""Documents returned stamped (Thursday) -- the success outcome."""
	clearance_step_name = clearance_step_name or kwargs.get("name") or kwargs.get("clearance_step")
	reference_no = reference_no or kwargs.get("visa_number") or kwargs.get("reference")
	step = _load_actionable_step(clearance_step_name, {"Embassy", "Kuwait Embassy", "Saudi Embassy"})
	if not _can_act_on_step(step):
		frappe.throw("Not permitted.", frappe.PermissionError)
	if step.status == "Stamped":
		return step.as_dict()
	# S-2: documents can only be Stamped after they were Submitted (the Mon->Thu cycle).
	if step.status != "Submitted":
		frappe.throw(f"Documents must be Submitted before they can be Stamped (this step is '{step.status}').", frappe.ValidationError)
	step.status = "Stamped"
	step.date_completed = today()
	step.completed_by = frappe.session.user
	if reference_no:
		step.reference_no = reference_no
	step.save(ignore_permissions=True)
	_close_open_todos(clearance_step_name)
	return step.as_dict()


@frappe.whitelist()
def reject_embassy_step(clearance_step_name, rejection_remark):
	"""Documents returned rejected (Thursday) -- requires a written remark
	(Clearance Step.validate() also enforces this as a backstop)."""
	if not rejection_remark:
		frappe.throw("A rejection remark is required.", frappe.ValidationError)
	step = frappe.get_doc("Clearance Step", clearance_step_name)
	if step.step_type not in ("Embassy", "Kuwait Embassy"):
		frappe.throw("Only meaningful for an Embassy clearance step.", frappe.ValidationError)
	if not _can_act_on_step(step):
		frappe.throw("Not permitted.", frappe.PermissionError)
	assert_clearance_step_not_terminal(step)
	# S-2: a Rejected outcome only makes sense for documents that were actually Submitted.
	if step.status != "Submitted":
		frappe.throw(f"Documents must be Submitted before they can be Rejected (this step is '{step.status}').", frappe.ValidationError)
	step.status = "Rejected"
	step.rejection_remark = rejection_remark
	step.date_completed = today()
	step.completed_by = frappe.session.user
	step.save(ignore_permissions=True)
	_close_open_todos(clearance_step_name)
	return step.as_dict()


@frappe.whitelist()
def reassign_clearance_step(clearance_step_name, new_officer):
	"""Part A.2: "reassignable by a manager if needed" — the escape hatch for the default
	auto-chain."""
	if not ({"Manager", "Admin", "System Manager"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	assert_clearance_step_not_terminal(frappe.get_doc("Clearance Step", clearance_step_name))
	assign_clearance_step(clearance_step_name, new_officer)
	return {"clearance_step": clearance_step_name, "assigned_to": new_officer}


@frappe.whitelist()
def list_my_clearance_steps(placement=None):
	"""A Clearance Officer / Ticketer's queue, optionally filtered by placement."""
	filters = {}
	if placement:
		filters["placement"] = placement
	steps = frappe.get_list(
		"Clearance Step",
		filters=filters,
		fields=[
			"name",
			"placement",
			"step_type",
			"status",
			"sequence_order",
			"is_mandatory",
			"date_started",
			"date_completed",
			"completed_by",
			"reference_no",
			"amount",
			"payment_status",
			"wakala_amount",
			"wakala_status",
			"rejection_remark",
		],
		order_by="sequence_order asc",
	)
	for s in steps:
		if s.get("step_type") == "Taeshir":
			active_injaz = frappe.get_all(
				"Injaz Attempt",
				filters={"parent": s["name"]},
				fields=["injaz_application_id", "appointment_date", "outcome", "injaz_amount"],
				order_by="creation desc",
				limit_page_length=1,
			)
			if active_injaz:
				s["injaz_application_id"] = active_injaz[0].get("injaz_application_id")
				s["appointment_date"] = active_injaz[0].get("appointment_date")
				s["injaz_outcome"] = active_injaz[0].get("outcome")
	return steps


@frappe.whitelist()
def list_assigned_steps(placement=None):
	return list_my_clearance_steps(placement=placement)


# ── Taeshir / Injaz attempts ───────────────────────────────────────────────────
# Injaz is data captured inside the Taeshir Clearance Step, now as a table of attempts
# (Injaz Attempt child rows). At most one row is "Active" at a time -- the current appointment
# and its Injaz payment. Missing/forfeiting an appointment closes the current attempt and opens a
# fresh one (new Application ID + appointment), because the Injaz website issues a new number and
# the fee already paid is lost. Reminders (watchdogs.taeshir_injaz_reminder_watchdog) and the
# Injaz PDF read the latest Active attempt.


def _get_active_injaz_attempt(step):
	"""The step's current (Active) Injaz attempt, or None. Falls back to the last row so a step
	whose only attempt was already Completed still resolves for read-only consumers (the PDF)."""
	attempts = step.get("injaz_attempts") or []
	active = [a for a in attempts if a.outcome == "Active"]
	if active:
		return active[-1]
	return attempts[-1] if attempts else None


def _require_taeshir_step(clearance_step_name):
	"""Load a Taeshir step the caller may act on, guarding type + terminal state uniformly."""
	if not clearance_step_name:
		frappe.throw("clearance_step_name is required.", frappe.ValidationError)
	step = frappe.get_doc("Clearance Step", clearance_step_name)
	if step.step_type != "Taeshir":
		frappe.throw("Injaz/appointment actions apply only to a Taeshir clearance step.", frappe.ValidationError)
	if not _can_act_on_step(step):
		frappe.throw("Not permitted.", frappe.PermissionError)
	assert_clearance_step_not_terminal(step)
	return step


@frappe.whitelist()
def set_taeshir_appointment(clearance_step_name=None, appointment_date=None, injaz_application_id=None, **kwargs):
	"""Book (or set details on) the current Taeshir appointment. Creates the Active Injaz attempt
	if none exists yet, otherwise updates it -- so this is the "first booking" entry point.
	Rescheduling an existing booking uses reschedule_taeshir_appointment; a missed/forfeited one
	uses forfeit_injaz_and_restart."""
	clearance_step_name = clearance_step_name or kwargs.get("name") or kwargs.get("clearance_step")
	appointment_date = appointment_date or kwargs.get("date")
	step = _require_taeshir_step(clearance_step_name)

	attempt = _get_active_injaz_attempt(step)
	if attempt is None or attempt.outcome != "Active":
		attempt = step.append("injaz_attempts", {"outcome": "Active", "payment_status": "Unpaid"})
	if appointment_date:
		attempt.appointment_date = appointment_date
	if injaz_application_id:
		attempt.injaz_application_id = injaz_application_id
	step.save(ignore_permissions=True)
	log_action("Clearance Step", step.name, f"[{step.title or step.name}] Taeshir appointment set: {appointment_date or '-'} / Injaz {injaz_application_id or '-'}")
	return step.as_dict()


@frappe.whitelist()
def reschedule_taeshir_appointment(clearance_step_name=None, new_appointment_date=None, cause=None, **kwargs):
	"""Move the current (Active) Taeshir appointment to a new date WITHOUT re-paying Injaz --
	the "unpaid or not-yet-due, free reschedule" case. Same Injaz Application ID / payment carry
	over; only the date changes (with the reason recorded on the attempt)."""
	clearance_step_name = clearance_step_name or kwargs.get("name") or kwargs.get("clearance_step")
	new_appointment_date = new_appointment_date or kwargs.get("appointment_date") or kwargs.get("date")
	if not new_appointment_date:
		frappe.throw("new_appointment_date is required.", frappe.ValidationError)
	step = _require_taeshir_step(clearance_step_name)

	attempt = _get_active_injaz_attempt(step)
	if attempt is None or attempt.outcome != "Active":
		frappe.throw("No active Taeshir appointment to reschedule. Book one with set_taeshir_appointment first.", frappe.ValidationError)
	attempt.appointment_date = new_appointment_date
	if cause:
		attempt.remark = f"Rescheduled: {cause}"
	step.save(ignore_permissions=True)
	log_action("Clearance Step", step.name, f"[{step.title or step.name}] Taeshir appointment rescheduled to {new_appointment_date}" + (f": {cause}" if cause else ""))
	return step.as_dict()


@frappe.whitelist()
def record_injaz_payment(clearance_step_name=None, amount=None, currency=None, receipt_number=None, paid_date=None, **kwargs):
	"""Mark the current (Active) Injaz attempt Paid, recording amount / currency / receipt. This is
	what clears the taeshir_injaz_payment_reminder for this attempt."""
	clearance_step_name = clearance_step_name or kwargs.get("name") or kwargs.get("clearance_step")
	step = _require_taeshir_step(clearance_step_name)

	attempt = _get_active_injaz_attempt(step)
	if attempt is None or attempt.outcome != "Active":
		attempt = step.append("injaz_attempts", {"outcome": "Active"})
	attempt.payment_status = "Paid"
	attempt.paid_date = paid_date or today()
	if amount is not None:
		attempt.injaz_amount = amount
	if currency:
		attempt.injaz_currency = currency
	if receipt_number:
		attempt.receipt_number = receipt_number
	step.save(ignore_permissions=True)
	log_action("Clearance Step", step.name, f"[{step.title or step.name}] Injaz paid: {amount or '-'} {currency or ''} (receipt {receipt_number or '-'})")
	return step.as_dict()


@frappe.whitelist()
def forfeit_injaz_and_restart(clearance_step_name=None, reason=None, new_appointment_date=None, new_injaz_application_id=None, **kwargs):
	"""The missed-appointment path: close the current attempt as Forfeited (fee lost) and open a
	fresh Active attempt with a new appointment date + (new) Injaz Application ID, unpaid. If the
	appointment was simply missed without loss dispute, the closed attempt is still marked
	Forfeited -- the money's gone either way once a re-payment is needed."""
	clearance_step_name = clearance_step_name or kwargs.get("name") or kwargs.get("clearance_step")
	if not reason:
		frappe.throw("A reason is required to forfeit and restart an Injaz attempt.", frappe.ValidationError)
	step = _require_taeshir_step(clearance_step_name)

	current = _get_active_injaz_attempt(step)
	prior_outcome = None
	if current is not None and current.outcome == "Active":
		# Forfeited = a Paid attempt whose fee is now lost; Missed = an unpaid appointment that
		# simply lapsed (nothing forfeited). (audit N-6)
		prior_outcome = "Forfeited" if current.payment_status == "Paid" else "Missed"
		current.outcome = prior_outcome
		current.remark = (current.remark + " | " if current.remark else "") + f"{prior_outcome}: {reason}"
	new_attempt = step.append(
		"injaz_attempts",
		{"outcome": "Active", "payment_status": "Unpaid", "appointment_date": new_appointment_date,
		 "injaz_application_id": new_injaz_application_id},
	)
	step.save(ignore_permissions=True)
	log_action("Clearance Step", step.name, f"[{step.title or step.name}] Injaz {prior_outcome or 'restarted'} ({reason}); new attempt {new_injaz_application_id or '-'} on {new_appointment_date or '-'}")
	return step.as_dict()


def _fmt_date(value):
	return formatdate(value, "dd/MM/yyyy") if value else ""


def _upper(value):
	return str(value).upper() if value else ""


def _injaz_context(step, placement, applicant):
	"""Flatten a Clearance Step (+ its Placement + Applicant) into the Saudi Embassy Consular
	Section (easyenjaz) Injaz visa-application form. Identity/passport come from the Applicant,
	sponsor/visa/employer/duration from the Placement, and the Injaz/Enjaz application numbers
	(the two barcodes) from the step/placement. destination is hardcoded ("Kingdom of Saudi
	Arabia") since render_injaz_pdf only ever runs for a Saudi placement to begin with. Fields the
	system genuinely doesn't hold (arrival/payment/dependents, etc.) still render blank, exactly
	like the real form before the consulate fills them in -- 2026-09-07: business_address,
	duration_of_stay, dealer_name and destination used to be in that blank list too, but the data
	was already sitting on Placement (employer_address/employment_site, contract_duration,
	saudi_agency_name) and just wasn't wired in."""
	nationality = applicant.nationality or "Ethiopia"
	# Left barcode = the visa number (derived at the Injaz/Taeshir stage from the Application ID).
	# Right barcode = the Application ID (E-number) captured on the Taeshir step itself.
	visa_number = placement.visa_number or ""
	active_attempt = _get_active_injaz_attempt(step)
	application_id = (active_attempt.injaz_application_id if active_attempt else "") or ""

	return {
		# ── header ──
		"left_barcode": code128_b_datauri(visa_number),
		"left_barcode_number": visa_number,
		"right_barcode": code128_b_datauri(application_id),
		"right_barcode_number": application_id,
		"sponsor_name": _upper(placement.sponsor_name),
		# Downsized to roughly print-quality for its ~118x138px displayed size (see
		# embed_image_datauri) -- source photos are routinely multi-MB phone-camera originals.
		"photo_src": embed_image_datauri(applicant.photograph, max_dimension=450),
		"emblem_src": asset_datauri("templates", "injaz_assets", "mofa_emblem.png"),
		"agency_full": ORIGIN_AGENCY_FULL,
		"agency_email": ORIGIN_AGENCY_EMAIL,
		# ── applicant ──
		"full_name": _upper(applicant.full_name),
		"date_of_birth": _fmt_date(applicant.date_of_birth),
		"place_of_birth": _upper(applicant.city),
		"past_nationality": nationality,
		"current_nationality": nationality,
		"sex": applicant.gender or "",
		"marital_status": applicant.marital_status or "",
		"sect": "",
		"religion": _RELIGION_MAP.get(applicant.religion, applicant.religion) or "",
		"qualification": _upper(applicant.education),
		"profession": _upper(applicant.target_job) or "HOUSE WORKER",
		"home_address": _upper(applicant.address),
		"business_address": _upper(placement.employer_address or placement.employment_site),
		# ── travel / passport ──
		"purpose": "Work",
		"place_of_issue": _upper(applicant.passport_issue_place) or "ADDIS ABABA",
		"date_of_issue": _fmt_date(applicant.passport_issue_date),
		"passport_no": applicant.passport_number or "",
		"date_of_expiry": _fmt_date(applicant.passport_expiry_date),
		"duration_of_stay": placement.contract_duration or "",
		"date_of_arrival": "",
		"date_of_departure": "",
		"mode_of_payment": "",
		"payment_no": "",
		"payment_date": "",
		"relationship": "",
		"destination": "Kingdom of Saudi Arabia",
		"dealer_name": _upper(placement.saudi_agency_name),
		# ── certification / footer ──
		"cert_date": _fmt_date(today()),
		"cert_name": _upper(applicant.full_name),
		"footer_date": formatdate(today(), "EEEE, MMMM d, yyyy"),
		"page_label": "Page 1 of 1",
	}


@frappe.whitelist()
def render_injaz_pdf(clearance_step_name=None, **kwargs):
	"""Generate the Embassy of Saudi Arabia Injaz application PDF for a Saudi clearance step.
	Open to any internal staff (Taeshir, Embassy, LMIS, management, etc.) -- not just the Taeshir
	officer -- so the Embassy desk and other staff can pull the paper. Foreign agencies cannot.
	The document is assembled fresh from the step's latest Injaz attempt plus the linked
	Placement/Applicant -- it is not stored, it streams straight back as a download."""
	clearance_step_name = clearance_step_name or kwargs.get("name") or kwargs.get("step_name")
	if not clearance_step_name:
		frappe.throw("clearance_step_name is required.", frappe.ValidationError)

	if frappe.session.user != "Administrator" and not (INTERNAL_STAFF_ROLES & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	step = frappe.get_doc("Clearance Step", clearance_step_name)

	placement = frappe.get_doc("Placement", step.placement)
	if placement.destination_country != "Saudi Arabia":
		frappe.throw("Injaz applies only to Saudi Arabia placements.", frappe.ValidationError)
	applicant = frappe.get_doc("Applicant", placement.applicant)

	pdf_bytes = render_pdf(INJAZ_TEMPLATE, _injaz_context(step, placement, applicant))
	log_action("Clearance Step", step.name, f"[{step.title or step.name}] Injaz PDF downloaded for {applicant.full_name}", event_type="Access")
	frappe.response["filename"] = f"Injaz_{placement.applicant}.pdf"
	frappe.response["filecontent"] = pdf_bytes
	frappe.response["type"] = "download"
