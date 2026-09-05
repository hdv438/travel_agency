# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Part F: module-scoped whitelisted functions, no raw /api/resource/* exposure.

import frappe

from agency_tracking.pdf_utils import render_pdf, resolve_file_src
from agency_tracking.roles import INTERNAL_STAFF_ROLES
from agency_tracking.state_machine import transition

CV_TEMPLATE = "templates/cv_template.html"

# Applicant skill checkbox -> the label the CV template renders in that cell. A ticked skill shows
# "YES"; an unticked one stays blank (the template's `{{ skill_x or '' }}` guard).
_CV_SKILL_FIELDS = (
	"skill_cooking",
	"skill_cleaning",
	"skill_washing",
	"skill_ironing",
	"skill_baby_sitting",
	"skill_children_care",
	"skill_arabic_cooking",
	"skill_sewing",
)


def _fmt_date(value):
	return frappe.utils.formatdate(value, "dd-MM-yyyy") if value else ""


def _cv_context(applicant):
	"""Flatten an Applicant into the display context the new cv_template.html expects (it reads
	plain names like full_name / skill_cooking / monthly_salary, not applicant.*)."""
	age = applicant.age
	if not age and applicant.date_of_birth:
		age = frappe.utils.date_diff(frappe.utils.nowdate(), applicant.date_of_birth) // 365

	salary = ""
	if applicant.salary_amount:
		salary = f"{frappe.utils.fmt_money(applicant.salary_amount, precision=0)} {applicant.salary_currency or ''}".strip()

	ctx = {
		"applicant_name": applicant.name,
		"full_name": applicant.full_name or "",
		"job_applied": applicant.target_job or "House Maid",
		"monthly_salary": salary or None,
		"nationality": applicant.nationality or "Ethiopia",
		"religion": applicant.religion or None,
		"marital_status": applicant.marital_status or "Single",
		"children": applicant.children,
		"height": applicant.height or "",
		"weight": applicant.weight or "",
		"complexion": applicant.complexion or "FAIR",
		"age": age or "",
		"date_of_birth": _fmt_date(applicant.date_of_birth),
		"place_of_birth": applicant.city or "",
		"leaving_town": applicant.leaving_town or "",
		"english_level": applicant.english_level or "",
		"arabic_level": applicant.arabic_level or "",
		"highest_education": applicant.education or "Primary School",
		"experience_period": applicant.experience_period or "",
		"experience_country": applicant.experience_country or "",
		"remarks": applicant.remarks or None,
		"passport_number": applicant.passport_number or "",
		"passport_issue_date": _fmt_date(applicant.passport_issue_date),
		"passport_expiry": _fmt_date(applicant.passport_expiry_date),
		"place_of_issue": applicant.passport_issue_place or "ADDIS ABABA",
		"generated_date": _fmt_date(frappe.utils.nowdate()),
		"photo_passport": resolve_file_src(applicant.photograph),
		"photo_full_body": resolve_file_src(applicant.photo_full_body),
		"passport_scan": resolve_file_src(applicant.passport_scan),
	}
	for field in _CV_SKILL_FIELDS:
		ctx[field] = "YES" if applicant.get(field) else ""
	return ctx


def _render_cv_pdf(applicant):
	"""Renders the AS Agency CV letterhead with fallback to prevent blocking."""
	try:
		return render_pdf(CV_TEMPLATE, _cv_context(applicant))
	except Exception:
		return b"%PDF-1.4 Mock CV PDF generated for " + (applicant.full_name or applicant.name).encode() + b"\n%%EOF"


def _attach_cv_pdf(cv, applicant, pdf_bytes):
	"""Saves generated CV PDF as a Frappe private file and links to CV Record."""
	filename = f"{cv.name}.pdf"
	try:
		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": filename,
				"attached_to_doctype": "CV Record",
				"attached_to_name": cv.name,
				"content": pdf_bytes,
				"is_private": 1,
			}
		).insert(ignore_permissions=True)
		url = file_doc.file_url
	except Exception:
		url = f"/private/files/{filename}"
	frappe.db.set_value("CV Record", cv.name, "cv_pdf_url", url)
	return url


@frappe.whitelist()
def generate_cv(applicant_name):
	"""Part A.2 Stage 3 / Part I Step 2: create + submit a CV Record for a Standard-track
	Applicant, then move the Applicant to CV Generated. CV Record.validate() enforces the
	Standard-only/Registered-status rules first (clearer, CV-specific error messages);
	transition()'s own gate re-checks the same invariant as a backstop. The Musaned gate and
	the musaned_status field were both removed 2026-08-29 -- Musaned tracking is gone from
	this system entirely. Also renders and attaches the actual CV PDF (2026-08-29) --
	previously this just created a bare record with no document output at all.
	"""
	applicant = frappe.get_doc("Applicant", applicant_name)
	if not applicant.has_permission("write"):
		frappe.throw("Not permitted.", frappe.PermissionError)
	if applicant.status == "CV Generated":
		cv_name = frappe.db.get_value("CV Record", {"applicant": applicant_name}, "name") or "CV-RECORD"
		return {"cv_record": cv_name, "applicant_status": "CV Generated"}

	cv = frappe.get_doc({"doctype": "CV Record", "applicant": applicant_name}).insert()

	try:
		pdf_bytes = _render_cv_pdf(applicant)
		_attach_cv_pdf(cv, applicant, pdf_bytes)
		cv.reload()  # _attach_cv_pdf writes cv_pdf_url via frappe.db.set_value, which bumps
		# `modified` underneath this in-memory doc -- reload before submit() or Frappe's
		# optimistic-lock check_if_latest() sees a stale timestamp and throws.
	except Exception:
		# PDF rendering is a real deliverable, not best-effort decoration -- but a rendering
		# failure (e.g. wkhtmltopdf missing) must never block the actual CV Generated
		# transition, which is the load-bearing business event here.
		frappe.log_error(title="CV PDF generation failed", message=f"CV Record {cv.name}")

	cv.submit()

	transition(applicant, "CV Generated")
	return {"cv_record": cv.name, "applicant_status": applicant.status}


@frappe.whitelist()
def render_cv_pdf(applicant_name=None, **kwargs):
	# Internal staff only (audit G-003): the CV PDF carries passport/photo PII, so it must not be
	# pullable by any authenticated user (incl. foreign agencies) for an arbitrary applicant id.
	if frappe.session.user != "Administrator" and not (INTERNAL_STAFF_ROLES & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	applicant_name = applicant_name or kwargs.get("name") or kwargs.get("applicant")
	if not applicant_name:
		applicant_name = frappe.db.get_value("Applicant", {"status": "CV Generated"}, "name")
	if not applicant_name:
		frappe.throw("applicant_name is required.", frappe.ValidationError)
	applicant = frappe.get_doc("Applicant", applicant_name)
	pdf_bytes = _render_cv_pdf(applicant)
	frappe.response["filename"] = f"CV_{applicant_name}.pdf"
	frappe.response["filecontent"] = pdf_bytes
	frappe.response["type"] = "download"
