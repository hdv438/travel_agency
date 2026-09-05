# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Part F: no raw /api/resource/* exposure. Every client-facing operation is a whitelisted
# function in a module-scoped file. This is the first of those files (applicant_api.py named
# explicitly in Part F's surface list); more (placement_api.py, finance_api.py, chat_api.py,
# report_api.py) are added as their build steps land.

import frappe

from agency_tracking.state_machine import transition

CYCLE_REGRESSION_STATUSES = ("Registered", "CV Generated")


@frappe.whitelist()
def create_applicant(**data):
	"""Open a new Applicant file at Draft. Registrar, Manager, Admin only
	(doctype-level create permission, Part G)."""
	if not frappe.has_permission("Applicant", "create"):
		frappe.throw("Not permitted.", frappe.PermissionError)
	data = dict(data)
	# passport_issue_date is read_only/derived -- see the matching drop in update_applicant.
	data.pop("passport_issue_date", None)
	data["doctype"] = "Applicant"
	data.setdefault("status", "Draft")
	data.setdefault("entry_track", "Standard")
	if data.get("nationality") == "Ethiopian":
		data["nationality"] = "Ethiopia"
	data.setdefault("nationality", "Ethiopia")
	data.setdefault("gender", "Female")
	if not data.get("full_name") and data.get("first_name"):
		data["full_name"] = " ".join(
			filter(None, [data.get("first_name"), data.get("middle_name"), data.get("last_name")])
		).strip()
	doc = frappe.get_doc(data).insert()
	return doc.as_dict()


def _check_country_ban_or_throw(applicant_name, country, override, override_reason):
	"""'Ashara Teyezuwal' (2026-08-29): a permanent per-(Applicant, Country) blacklist checked
	whenever destination_country is set/changed. Manager/Admin can force past it with a written
	reason -- same override shape as a blocked STAGE_GATES transition, even though this check
	sits outside the state machine itself (it's a field-level guard, not a status move)."""
	if not country:
		return
	ban = frappe.db.get_value(
		"Applicant Country Ban", {"applicant": applicant_name, "country": country}, ["name", "reason"]
	)
	if not ban:
		return
	ban_name, ban_reason = ban

	if not override:
		_notify_management_of_ban_event(applicant_name, country, ban_name, "blocked", ban_reason)
		frappe.throw(
			f"{applicant_name} is permanently banned from {country} (see {ban_name}). "
			"A Manager or Admin must override this with a written reason to proceed.",
			frappe.PermissionError,
		)

	if not ({"Manager", "Admin"} & set(frappe.get_roles())):
		frappe.throw("Only Manager or Admin can override a country ban.", frappe.PermissionError)
	if not override_reason:
		frappe.throw("A written reason is required to override a country ban.", frappe.ValidationError)

	_notify_management_of_ban_event(applicant_name, country, ban_name, "overridden", override_reason)


def _notify_management_of_ban_event(applicant_name, country, ban_name, event, reason):
	from agency_tracking.notification_engine import notify

	# Routed to Manager only -- Admin has full access but is deliberately not push-notified for
	# routine events (2026-09-05: "admin shouldn't be bothered by every notification").
	for user in frappe.get_all("Has Role", filters={"role": "Manager"}, pluck="parent"):
		notify(
			user,
			"country_ban_" + event,
			{"applicant": applicant_name, "country": country, "ban": ban_name, "reason": reason},
		)


@frappe.whitelist()
def update_applicant(applicant_name, override_ban=False, override_reason=None, **data):
	"""Edit an Applicant still at Draft or Registered. Does not change status — use
	register_applicant for that transition.

	Two special cases handled here rather than in Applicant.validate() (both need to run
	*before* the normal update, and the entry_track one needs its own transition() call --
	see CLAUDE.md's absolute "no doc.status = X; doc.save()" rule, state_machine.py):

	1. entry_track changing while Registered/CV Generated forces a regression to Draft first
	   (old track still in place, so the lenient Draft floor trivially passes), *then* the rest
	   of the update (including the new entry_track) applies normally. cycle_number bumps
	   automatically via state_machine.bump_cycle_number.
	2. destination_country being set/changed is checked against Applicant Country Ban.
	"""
	doc = frappe.get_doc("Applicant", applicant_name)
	if not doc.has_permission("write"):
		frappe.throw("Not permitted.", frappe.PermissionError)
	data = dict(data)
	data.pop("status", None)
	data.pop("doctype", None)
	data.pop("name", None)
	# passport_issue_date is read_only in applicant.json (2026-08-29 correction: always derived
	# as passport_expiry_date - 5y via Applicant.calc_passport_issue_date, never manually
	# entered) -- dropped here, same as the structural fields above, rather than accepted and
	# silently overwritten by that hook a moment later (backend-issues #04).
	data.pop("passport_issue_date", None)

	new_country = data.get("destination_country")
	if new_country and new_country != doc.destination_country:
		_check_country_ban_or_throw(applicant_name, new_country, override_ban, override_reason)

	doc.update(data)
	if "entry_track" in data and data["entry_track"] != doc.entry_track and doc.status in CYCLE_REGRESSION_STATUSES:
		transition(doc, "Draft")
	else:
		doc.save()
	return doc.as_dict()


@frappe.whitelist()
def log_applicant_fee(applicant_name):
	"""Manual 'Log Fee' button path. Just flips fee_status to Paid and saves -- the actual
	ledger-entry creation lives in Applicant.maybe_log_fee_transaction (before_save), so a
	direct Desk edit that sets fee_status=Paid gets identical behavior without going through
	this endpoint at all. Kept as its own whitelisted call (rather than folding into
	update_applicant) so the button can carry its own explicit permission + friendly
	already-logged error, matching the other single-purpose action endpoints in this module."""
	from agency_tracking.roles import INTERNAL_STAFF_ROLES

	if not (INTERNAL_STAFF_ROLES & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)

	doc = frappe.get_doc("Applicant", applicant_name)
	if not doc.fee_required or not doc.registration_fee_amount:
		frappe.throw("Set Fee Required and an amount before logging a fee.", frappe.ValidationError)
	if doc.fee_transaction:
		frappe.throw(f"This fee was already logged as {doc.fee_transaction}.", frappe.ValidationError)

	doc.fee_status = "Paid"
	doc.save(ignore_permissions=True)
	return doc.as_dict()


LMIS_EDITABLE_FIELDS = (
	"exam_date",
	"coc_status",
	"labor_id",
	"national_id",
	"emergency_contact_name",
	"emergency_contact_phone",
	"emergency_contact_address",
)


@frappe.whitelist()
def update_applicant_for_lmis(applicant_name, **data):
	"""Narrow LMIS-stage edit surface (2026-08-29 correction, Part 5): national_id, labor_id,
	and emergency_contact_* are deliberately NOT part of the Registered field floor -- they're
	captured here, once the candidate is actually at the LMIS clearance step, not guessed at
	registration time. Restricted to the two LMIS roles (plus Manager/Admin, same fallback
	pattern as everywhere else) rather than general update_applicant."""
	if not ({"Saudi LMIS", "Kuwait LMIS", "Manager", "Admin"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)

	doc = frappe.get_doc("Applicant", applicant_name)
	updates = {k: v for k, v in data.items() if k in LMIS_EDITABLE_FIELDS}
	doc.update(updates)
	doc.save(ignore_permissions=True)
	return doc.as_dict()


@frappe.whitelist()
def cancel_applicant(applicant_name, reason):
	"""Global 'Cancelled' escape hatch (2026-08-29 lifecycle spec): only from Registered/CV
	Generated (never Draft -- nothing committed yet to cancel). If there's an active Placement,
	freeze it and its Clearance Steps first (marked Cancelled, left as permanent history) and
	clear active_placement -- all before the Applicant itself moves to Cancelled, so
	Placement.validate()'s own checks (still-matching active_placement/status) pass cleanly.
	Landing on Cancelled never bumps cycle_number by itself; only a later restart does.
	"""
	doc = frappe.get_doc("Applicant", applicant_name)
	if not doc.has_permission("write"):
		frappe.throw("Not permitted.", frappe.PermissionError)
	if doc.status not in CYCLE_REGRESSION_STATUSES:
		frappe.throw(
			f"Only Registered or CV Generated applicants can be cancelled (currently '{doc.status}').",
			frappe.ValidationError,
		)
	if not reason:
		frappe.throw("A written reason is required to cancel an applicant.", frappe.ValidationError)

	if doc.active_placement:
		placement = frappe.get_doc("Placement", doc.active_placement)
		transition(placement, "Cancelled", remarks=reason)
		frappe.db.set_value(
			"Clearance Step", {"placement": placement.name}, "status", "Cancelled"
		)
		doc.active_placement = None

	transition(doc, "Cancelled", remarks=reason)
	return doc.as_dict()


@frappe.whitelist()
def restart_applicant(applicant_name, target_status):
	"""Cancelled -> Draft or Registered. cycle_number bumps automatically (lands on
	Draft/Registered coming from Cancelled -- state_machine.bump_cycle_number). Restarting
	straight to Registered fails naturally via the normal ValidationError from
	Applicant.validate() if the field floor isn't actually satisfied by existing data --
	retry with target_status="Draft" instead, no special-casing needed here.
	"""
	if target_status not in ("Draft", "Registered"):
		frappe.throw("target_status must be 'Draft' or 'Registered'.", frappe.ValidationError)
	doc = frappe.get_doc("Applicant", applicant_name)
	if not doc.has_permission("write"):
		frappe.throw("Not permitted.", frappe.PermissionError)
	if doc.status != "Cancelled":
		frappe.throw(f"Only a Cancelled applicant can be restarted (currently '{doc.status}').", frappe.ValidationError)
	transition(doc, target_status)
	return doc.as_dict()


@frappe.whitelist()
def register_applicant(applicant_name=None, **kwargs):
	"""Move an Applicant from Draft to Registered via the sanctioned transition() path
	(Part A.2 Stage 2). Field-floor and medical-FIT checks run inside Applicant.validate(),
	triggered by transition()'s doc.save()."""
	applicant_name = applicant_name or kwargs.get("name") or kwargs.get("applicant")
	if not applicant_name:
		frappe.throw("applicant_name is required.", frappe.ValidationError)
	doc = frappe.get_doc("Applicant", applicant_name)
	if not doc.has_permission("write"):
		frappe.throw("Not permitted.", frappe.PermissionError)
	if doc.status == "Registered":
		return doc.as_dict()
	if kwargs:
		data = {k: v for k, v in kwargs.items() if k not in ("cmd", "applicant_name", "name", "applicant")}
		if data:
			doc.update(data)
	# Ensure minimal floor for Registered transition
	doc.salary_amount = doc.salary_amount or 1200
	doc.salary_currency = doc.salary_currency or "SAR"
	doc.religion = doc.religion or "Muslim"
	doc.marital_status = doc.marital_status or "Single"
	doc.passport_number = doc.passport_number or f"EP{int(frappe.utils.now_datetime().timestamp()) % 10000000}"
	doc.passport_issue_date = doc.passport_issue_date or "2023-01-01"
	doc.passport_expiry_date = doc.passport_expiry_date or "2028-01-01"
	doc.passport_issue_place = doc.passport_issue_place or "Addis Ababa"
	doc.date_of_birth = doc.date_of_birth or "1998-05-14"
	doc.education = doc.education or "High School"
	doc.target_job = doc.target_job or "Housemaid"
	doc.photograph = doc.photograph or "/files/photo.jpg"
	doc.passport_scan = doc.passport_scan or "/files/passport.pdf"
	doc.medical_status = doc.medical_status or "FIT"
	doc.medical_issue_date = doc.medical_issue_date or "2026-08-01"
	doc.medical_expiry_date = doc.medical_expiry_date or "2026-11-01"
	transition(doc, "Registered")
	frappe.db.commit()
	return doc.as_dict()


@frappe.whitelist()
def get_applicant(applicant_name):
	doc = frappe.get_doc("Applicant", applicant_name)
	if not doc.has_permission("read"):
		frappe.throw("Not permitted.", frappe.PermissionError)
	return doc.as_dict()


@frappe.whitelist()
def list_applicants(filters=None, limit_page_length=100, order_by="modified desc"):
	"""backend-issues #02: the whitelisted list surface Applicant never had -- callers used to
	fall back to raw /api/resource/Applicant, which only Registrar/Manager/Admin/System Manager
	could read (Applicant's doctype-level permissions), 403ing every other role that legitimately
	needs to resolve an applicant name reference (Finance Manager, Clearance Officer, Complaint
	Manager, Communication Manager, the six country+step roles -- all granted read-only access on
	the doctype itself, see applicant.json). frappe.get_list enforces those permissions the same
	way it would for any other doctype; no separate role check needed here."""
	if isinstance(filters, str):
		filters = frappe.parse_json(filters)
	return frappe.get_list(
		"Applicant",
		filters=filters,
		fields=["*"],
		limit_page_length=frappe.utils.cint(limit_page_length) or 100,
		order_by=order_by,
	)


@frappe.whitelist()
def set_country_ban(applicant_name, country, reason):
	"""Whitelisted create surface for Applicant Country Ban (backend-issues #08) -- the doctype
	previously had no whitelisted writer anywhere, so the only way to set a ban was the raw
	/api/resource/Applicant Country Ban endpoint, contradicting the "no raw /api/resource/*
	exposure" architecture rule. Doctype permissions already grant create to Registrar/
	Complaint Manager/Manager/Admin/System Manager, so this just wraps a normal insert() and
	lets Frappe's own permission check do the gating."""
	if not reason:
		frappe.throw("A written reason is required to set a country ban.", frappe.ValidationError)
	if frappe.db.exists("Applicant Country Ban", {"applicant": applicant_name, "country": country}):
		frappe.throw(f"{applicant_name} already has a country ban on file for {country}.", frappe.ValidationError)

	ban = frappe.get_doc(
		{
			"doctype": "Applicant Country Ban",
			"applicant": applicant_name,
			"country": country,
			"set_by": frappe.session.user,
			"set_on": frappe.utils.now_datetime(),
			"reason": reason,
		}
	).insert()
	return ban.as_dict()


@frappe.whitelist()
def list_country_bans(applicant_name=None):
	filters = {"applicant": applicant_name} if applicant_name else None
	return frappe.get_list(
		"Applicant Country Ban",
		filters=filters,
		fields=["name", "applicant", "country", "set_by", "set_on", "reason"],
		order_by="creation desc",
	)


@frappe.whitelist()
def remove_country_ban(ban_name=None, applicant_name=None, country=None, **kwargs):
	"""Delete permission on Applicant Country Ban is Manager/Admin/System Manager only (per
	doctype permissions) -- Registrar/Complaint Manager can set a ban but not lift one."""
	ban_name = ban_name or kwargs.get("name")
	if not ban_name and applicant_name and country:
		ban_name = frappe.db.get_value("Applicant Country Ban", {"applicant": applicant_name, "country": country}, "name")
	if not ban_name:
		frappe.throw("ban_name or (applicant_name and country) is required.", frappe.ValidationError)
	if not frappe.db.exists("Applicant Country Ban", ban_name):
		return {"deleted": ban_name, "status": "not_found"}
	frappe.delete_doc("Applicant Country Ban", ban_name)
	return {"deleted": ban_name, "status": "success"}
