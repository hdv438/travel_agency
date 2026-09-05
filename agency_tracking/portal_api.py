# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Part F: module-scoped whitelisted functions, no raw /api/resource/* exposure. Foreign Agency
# users get NO direct doctype permissions on Applicant/Placement/Contractor (see the doctype
# JSONs) — every bit of portal access is mediated here, with its own explicit role/ownership
# checks, per Part G ("Foreign Agency (portal): Own country's catalog, own placements...").

import frappe

from agency_tracking.state_machine import lock_applicant_row

# Non-PII browsing fields only (business names/skills, not passport/national ID/phone/address/
# emergency contacts) — the spec doesn't enumerate an exact portal field list, so this is a
# judgment call; tightened rather than loosened since the alternative is leaking PII to a
# third-party agency before any commission has even been agreed.
PORTAL_FIELDS = [
	"name",
	"full_name",
	"gender",
	"nationality",
	"date_of_birth",
	"age",
	"target_job",
	"education",
	"photograph",
	"photo_full_body",
	"destination_country",
	"religion",
	"marital_status",
	"experience_country",
	"years_of_experience",
	"experience_video",
]

# Richer, still strictly non-PII profile an agency may pull for a SINGLE candidate it is allowed
# to view (portal_api.get_candidate_detail). Adds physical attributes, education/experience, the
# skills matrix, the self-intro experience video and salary expectation on top of PORTAL_FIELDS.
# Deliberately excludes every direct-identifier / contact / location PII field (passport_number,
# national_id, labor_id, phone/alternate_phone, email, address, emergency_contact_*, city/region/
# sub_region/leaving_town) and all internal-only fields (fees, medical_remarks, remarks) — a
# third-party agency browsing a catalog has no need for any of those before a placement exists.
PORTAL_DETAIL_FIELDS = [
	"name",
	"full_name",
	"gender",
	"nationality",
	"date_of_birth",
	"age",
	"height",
	"weight",
	"complexion",
	"photograph",
	"photo_full_body",
	"experience_video",
	"target_job",
	"education",
	"destination_country",
	"religion",
	"marital_status",
	"children",
	"salary_amount",
	"salary_currency",
	"institution",
	"graduation_year",
	"english_level",
	"arabic_level",
	"current_employer",
	"years_of_experience",
	"experience_country",
	"experience_period",
	"education_remarks",
	"coc_status",
	"skill_cleaning",
	"skill_cooking",
	"skill_washing",
	"skill_ironing",
	"skill_baby_sitting",
	"skill_children_care",
	"skill_arabic_cooking",
	"skill_elderly_care",
	"skill_driving",
	"skill_sewing",
]

# Fields a Foreign Agency may see on its OWN placements (portal_api.list_my_placements). Lifecycle,
# contract/visa identifiers, medical checkpoints and travel logistics — the things an agency needs
# to track its own workers. Deliberately excludes internal cost/commission fields (ticket_cost,
# reschedule_cost, manual_commission_*) and employer/sponsor PII (national IDs, addresses, the
# cross-check agency-name/license fields) that are internal-staff-only.
PORTAL_PLACEMENT_FIELDS = [
	"name",
	"applicant",
	"contractor",
	"destination_country",
	"status",
	"cv_record",
	"cycle_number",
	"contract_file",
	"contract_signed_date",
	"contract_number",
	"visa_number",
	"employer_name",
	"employment_site",
	"contract_duration",
	"contract_salary_amount",
	"contract_salary_currency",
	"visa_file",
	"visa_type",
	"visa_issue_date",
	"visa_expiry_date",
	"visa_reference_number",
	"sponsor_name",
	"medical_selected_status",
	"medical_selected_examination_date",
	"medical_2_status",
	"medical_2_examination_date",
	"ticket_number",
	"flight_date",
	"is_rescheduled",
	"reschedule_date",
	"reschedule_cause",
	"is_free_replacement",
	"free_replacement_for_complaint",
	"departed_on",
]


def _get_contractor_for_session_user(contractor_override=None):
	is_internal = frappe.session.user == "Administrator" or bool(
		{"Manager", "Admin", "System Manager"} & set(frappe.get_roles())
	)
	if "Foreign Agency" in frappe.get_roles() and not is_internal:
		# Strictly tenant-scoped: Foreign Agency callers MUST ONLY ever access their own linked Contractor.
		contractor_name = frappe.db.get_value("Contractor", {"user": frappe.session.user}, "name")
		if not contractor_name:
			frappe.throw("Foreign agency user is not linked to any Contractor.", frappe.PermissionError)
		if contractor_override and contractor_override != contractor_name:
			frappe.throw("Not permitted to access data for another agency.", frappe.PermissionError)
		return frappe.get_doc("Contractor", contractor_name)

	if contractor_override:
		return frappe.get_doc("Contractor", contractor_override)

	if is_internal:
		frappe.throw(
			"A contractor must be specified for this operation (pass contractor_name / contractor).",
			frappe.ValidationError,
		)
	frappe.throw("Not permitted.", frappe.PermissionError)



def _is_internal_placement_reader():
	"""Internal staff who legitimately see every placement regardless of Contractor — the same
	set that can override country scoping in select_candidate. Foreign Agency is deliberately
	NOT here: it is tenant-scoped to its own Contractor."""
	return frappe.session.user == "Administrator" or bool(
		{"Manager", "Admin", "System Manager"} & set(frappe.get_roles())
	)


def _own_placement_or_403(placement_name, contractor):
	"""Multi-tenant isolation gate for returning an *existing* Placement to a portal caller.

	Idempotent re-selection by the placement's real owner returns the placement; internal staff
	(_is_internal_placement_reader) also get it. Any other agency gets a bare PermissionError —
	no placement name, contractor, status, financial, clearance, ticket, or any other field is
	read or returned. This is the single choke point both select_candidate return paths funnel
	through, so a row-lock/idempotency race cannot bypass the ownership check."""
	owner_contractor = frappe.db.get_value("Placement", placement_name, "contractor")
	if _is_internal_placement_reader() or owner_contractor == contractor.name:
		return frappe.get_doc("Placement", placement_name).as_dict()
	frappe.throw("Not permitted.", frappe.PermissionError)


def _get_latest_cv_record(applicant_name):
	return frappe.db.get_value(
		"CV Record",
		{"applicant": applicant_name, "docstatus": 1},
		"name",
		order_by="creation desc",
	)


@frappe.whitelist()
def list_portal_candidates(target_job=None, gender=None, **kwargs):
	"""business-workflow-srs.md: "Contractors can browse available registered candidates (CV
	status), filtered by their quota country." Only CV Generated candidates (Part A.2 Stage 4);
	only the contractor's own country."""
	allowed_roles = {"Foreign Agency", "Manager", "Admin", "System Manager", "Registrar"}
	if frappe.session.user != "Administrator" and not (allowed_roles & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	filters = {
		"status": "CV Generated",
		"entry_track": "Standard",
		# Candidate exclusivity: the instant an applicant is selected by any agency, active_placement
		# is set and they must leave every agency's marketplace. Enforced backend-side here (not in
		# the frontend) so a placed/reserved candidate is never returned to an unrelated agency.
		"active_placement": ["is", "not set"],
	}
	is_internal = frappe.session.user == "Administrator" or bool(
		{"Manager", "Admin", "System Manager"} & set(frappe.get_roles())
	)
	if "Foreign Agency" in frappe.get_roles() and not is_internal:
		contractor = _get_contractor_for_session_user()
		filters["destination_country"] = contractor.country
	elif kwargs.get("contractor_name") or kwargs.get("contractor"):
		contractor = _get_contractor_for_session_user(contractor_override=kwargs.get("contractor_name") or kwargs.get("contractor"))
		filters["destination_country"] = contractor.country
	elif kwargs.get("destination_country"):
		filters["destination_country"] = kwargs.get("destination_country")
	if target_job:
		filters["target_job"] = target_job
	if gender:
		filters["gender"] = gender

	return frappe.get_list(
		"Applicant",
		filters=filters,
		fields=PORTAL_FIELDS,
		ignore_permissions=True,
	)


def _assert_can_view_candidate(applicant_name):
	"""Shared permission gate for viewing a single portal candidate's detail OR photo. A Foreign
	Agency may only view a candidate currently available in its OWN destination country (Standard,
	CV Generated, not yet locked), OR one whose active Placement it already owns. Any other
	candidate is a bare 403. Internal staff / Registrar / management may view any. Returns the
	candidate's scope row."""
	allowed_roles = {"Foreign Agency", "Manager", "Admin", "System Manager", "Registrar"}
	if frappe.session.user != "Administrator" and not (allowed_roles & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)

	scope = frappe.db.get_value(
		"Applicant",
		applicant_name,
		["name", "status", "entry_track", "destination_country", "active_placement"],
		as_dict=True,
	)
	if not scope:
		frappe.throw(f"{applicant_name} not found.", frappe.DoesNotExistError)

	if "Foreign Agency" in frappe.get_roles() and not _is_internal_placement_reader():
		contractor = _get_contractor_for_session_user()
		owns_placement = bool(scope.active_placement) and (
			frappe.db.get_value("Placement", scope.active_placement, "contractor") == contractor.name
		)
		available = (
			scope.entry_track == "Standard"
			and scope.status == "CV Generated"
			and not scope.active_placement
			and scope.destination_country == contractor.country
		)
		if not (available or owns_placement):
			frappe.throw("Not permitted.", frappe.PermissionError)
	return scope


@frappe.whitelist()
def get_candidate_detail(applicant_name=None, **kwargs):
	"""Rich, non-PII profile for a single catalog candidate (experience video, skills matrix,
	education/experience, physical attributes, salary expectation — PORTAL_DETAIL_FIELDS).

	Same tenant/country scoping as the marketplace (see _assert_can_view_candidate)."""
	applicant_name = applicant_name or kwargs.get("applicant") or kwargs.get("name")
	if not applicant_name:
		frappe.throw("applicant_name is required.", frappe.ValidationError)
	_assert_can_view_candidate(applicant_name)
	return frappe.db.get_value("Applicant", applicant_name, PORTAL_DETAIL_FIELDS, as_dict=True)


# The ONLY candidate images an agency may load. Sensitive files (passport_scan, contract, visa) are
# never served here.
CANDIDATE_PHOTO_KINDS = {"photograph", "photo_full_body"}


@frappe.whitelist()
def get_candidate_photo(applicant_name=None, kind="photograph", **kwargs):
	"""Serve a portal candidate's marketing photo to an agency allowed to view that candidate (same
	gate as get_candidate_detail). Agencies can't read the underlying (private) File docs directly,
	so this is their only path to these images -- and it exposes ONLY photograph / photo_full_body,
	never passport/contract/visa files.

	Storage-agnostic, so it's correct both now and after the R2 cutover: a local Frappe file is
	streamed inline; a photo already offloaded to R2 (an absolute public URL) is served via a
	redirect. Missing photo -> 404."""
	applicant_name = applicant_name or kwargs.get("applicant") or kwargs.get("name")
	kind = kind if kind in CANDIDATE_PHOTO_KINDS else "photograph"
	if not applicant_name:
		frappe.throw("applicant_name is required.", frappe.ValidationError)
	_assert_can_view_candidate(applicant_name)

	value = frappe.db.get_value("Applicant", applicant_name, kind)
	if not value:
		frappe.throw("No photo on file for this candidate.", frappe.DoesNotExistError)

	# R2 / any absolute URL: send the browser (or the frontend proxy) straight to the public object.
	if value.startswith("http://") or value.startswith("https://"):
		frappe.local.response["type"] = "redirect"
		frappe.local.response["location"] = value
		return

	# Local Frappe file: stream the bytes ourselves (the agency has no direct File read permission,
	# but our own gate above already authorized this specific candidate's photo).
	file_name = frappe.db.get_value("File", {"file_url": value}, "name")
	if not file_name:
		frappe.throw("Photo file not found.", frappe.DoesNotExistError)
	file_doc = frappe.get_doc("File", file_name)
	frappe.local.response.filename = file_doc.file_name
	frappe.local.response.filecontent = file_doc.get_content()
	frappe.local.response.type = "download"


@frappe.whitelist()
def select_candidate(applicant_name=None, free_replacement_for_complaint=None, contractor_name=None, **kwargs):
	"""Part A.2 Stage 4: atomic, globally exclusive selection. The instant one agency selects
	a candidate, they vanish from every other agency's view — enforced here with a row lock
	(SELECT ... FOR UPDATE) so two concurrent selections can't both see the candidate as free.
	"""
	applicant_name = applicant_name or kwargs.get("applicant")
	contractor_name = contractor_name or kwargs.get("contractor")
	if not applicant_name:
		frappe.throw("applicant_name is required.", frappe.ValidationError)

	contractor = _get_contractor_for_session_user(contractor_override=contractor_name)

	applicant = frappe.get_doc("Applicant", applicant_name)
	if applicant.active_placement:
		# CRITICAL multi-tenant gate: only the owning Contractor (or internal staff) may see an
		# already-existing Placement. A different agency selecting an already-taken applicant gets
		# a bare 403 — never the other agency's Placement document or any of its metadata.
		return _own_placement_or_403(applicant.active_placement, contractor)
	if applicant.entry_track != "Standard":
		frappe.throw("Only Standard-track candidates are selected via the portal.", frappe.ValidationError)
	if applicant.status != "CV Generated":
		frappe.throw(
			f"{applicant_name} is not currently portal-visible (status: {applicant.status}).",
			frappe.ValidationError,
		)
	if applicant.destination_country != contractor.country and frappe.session.user != "Administrator" and not ({"Manager", "Admin", "System Manager"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)

	if free_replacement_for_complaint:
		complaint = frappe.get_doc("Complaint", free_replacement_for_complaint)
		if complaint.status != "Returned - Free Replacement Required":
			frappe.throw(
				f"{free_replacement_for_complaint} is not an approved free-replacement complaint "
				f"(status: {complaint.status}).",
				frappe.ValidationError,
			)
		if complaint.contractor != contractor.name:
			frappe.throw("Not permitted.", frappe.PermissionError)
		if frappe.db.exists("Placement", {"free_replacement_for_complaint": free_replacement_for_complaint}):
			frappe.throw(
				f"{free_replacement_for_complaint}'s free replacement has already been used.",
				frappe.ValidationError,
			)

	# Row lock held until this request's transaction commits — a second, concurrent
	# select_candidate() for the same applicant blocks here until the first is done, then
	# sees active_placement already set and is rejected. Without this, two agencies could
	# both read active_placement as empty before either had written it.
	lock_applicant_row(applicant_name)
	current_lock = frappe.db.get_value("Applicant", applicant_name, "active_placement")
	if current_lock:
		# Same isolation gate as the pre-lock path — a placement that appeared while we waited on
		# the row lock is returned only if it is ours (idempotent), otherwise a bare 403. This is
		# what stops the lock/idempotency window from leaking another agency's placement.
		return _own_placement_or_403(current_lock, contractor)

	placement = frappe.get_doc(
		{
			"doctype": "Placement",
			"applicant": applicant_name,
			"contractor": contractor.name,
			"destination_country": applicant.destination_country,
			"status": "Selected",
			"cv_record": _get_latest_cv_record(applicant_name),
			"is_free_replacement": 1 if free_replacement_for_complaint else 0,
			"free_replacement_for_complaint": free_replacement_for_complaint,
		}
	).insert(ignore_permissions=True)

	frappe.db.set_value("Applicant", applicant_name, "active_placement", placement.name)
	return placement.as_dict()


@frappe.whitelist()
def list_my_placements(status=None, limit_page_length=100, limit_start=0, order_by="modified desc", contractor_name=None, **kwargs):
	"""Foreign Agency's own placement read surface (backend-issues, multi-tenant audit).

	placement_api.list_placements is internal-staff-only (Placement's doctype-level read grants
	never include Foreign Agency, by design — Part F/G), so agencies 403 there. Rather than
	weaken that grant, this dedicated portal op derives the Contractor from the session user
	(never from a caller-supplied contractor id) and returns ONLY that Contractor's placements,
	limited to PORTAL_PLACEMENT_FIELDS. Unlinked Foreign Agency users 403 via
	_get_contractor_for_session_user. Tenant isolation is enforced entirely server-side."""
	contractor = _get_contractor_for_session_user(contractor_override=contractor_name or kwargs.get("contractor"))
	filters = {"contractor": contractor.name}
	if status:
		filters["status"] = status
	return frappe.get_all(
		"Placement",
		filters=filters,
		fields=PORTAL_PLACEMENT_FIELDS,
		limit_page_length=frappe.utils.cint(limit_page_length) or 100,
		limit_start=frappe.utils.cint(limit_start),
		order_by=order_by,
		ignore_permissions=True,
	)


@frappe.whitelist()
def list_my_wakala_requests(contractor_name=None, **kwargs):
	"""New (2026-08-29): a Contractor-scoped list of every unpaid Wakala-bearing Embassy step
	for their own placements — the page the watchdog/manual reminders (watchdogs.
	wakala_reminder_watchdog) are actually pointing them at. Mirrors list_my_clearance_steps()'s
	pattern for the internal-staff side."""
	contractor = _get_contractor_for_session_user(contractor_override=contractor_name or kwargs.get("contractor"))
	placement_names = frappe.get_all("Placement", filters={"contractor": contractor.name}, pluck="name")
	if not placement_names:
		return []
	return frappe.get_all(
		"Clearance Step",
		filters={
			"placement": ["in", placement_names],
			"step_type": "Embassy",
			"wakala_status": ["!=", "Paid"],
		},
		fields=["name", "placement", "wakala_amount", "wakala_status", "status"],
		ignore_permissions=True,
	)
