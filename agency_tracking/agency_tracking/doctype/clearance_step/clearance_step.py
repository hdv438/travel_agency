# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE

import frappe
from frappe.model.document import Document

# 2026-08-29: role-based access replaces per-row ToDo *permission* for the six country+step
# roles (Clearance Officer/Ticketer keep the old ToDo-scoped model). Anyone holding the mapped
# role can read/act on every Clearance Step row of that type, full stop -- ToDo assignment is
# kept only for the notification/queue UX (clearance_engine.create_clearance_steps still
# creates one per matching-role user), never as the permission gate, so the two mechanisms
# can't disagree with each other.
CLEARANCE_ROLE_BY_STEP_TYPE = {
	"LMIS Clearance": "Saudi LMIS",
	"Taeshir": "Saudi Taeshir",
	"Embassy": "Saudi Embassy",
	"Kuwait LMIS": "Kuwait LMIS",
	"Telesign": "Kuwait Telesign",
	"Kuwait Embassy": "Kuwait Embassy",
}


class ClearanceStep(Document):
	def validate(self):
		if self.status == "Rejected" and not self.rejection_remark:
			frappe.throw(
				"A rejection remark is required when an Embassy step is Rejected.",
				frappe.ValidationError,
			)

	def before_save(self):
		from agency_tracking.storage_engine import migrate_attach_to_r2

		applicant_name = frappe.db.get_value("Placement", self.placement, "applicant") if self.placement else None
		# Injaz receipt photos now live per-attempt (Injaz Attempt.receipt_photo).
		for attempt in self.get("injaz_attempts") or []:
			migrate_attach_to_r2(attempt, "receipt_photo", "injaz", applicant_name=applicant_name)
		for payment in self.get("payments") or []:
			migrate_attach_to_r2(payment, "receipt_url", "finance-receipts", applicant_name=applicant_name)


def get_permission_query_conditions(user):
	"""Part G, extended 2026-08-29: Clearance Officer / Ticketer still see rows only via ToDo
	assignment (per-row, cross-step-type). The six country+step roles instead see *every* row
	of their own step_type, regardless of ToDo assignment."""
	if not user:
		user = frappe.session.user
	roles = set(frappe.get_roles(user))
	if {"Admin", "Manager", "System Manager"} & roles:
		return ""

	conditions = []
	if {"Clearance Officer", "Ticketer"} & roles:
		conditions.append(
			"`tabClearance Step`.name in ("
			"select reference_name from `tabToDo` "
			"where reference_type='Clearance Step' "
			f"and allocated_to={frappe.db.escape(user)} and status='Open')"
		)
	matching_step_types = [
		step_type for step_type, role in CLEARANCE_ROLE_BY_STEP_TYPE.items() if role in roles
	]
	if matching_step_types:
		escaped = ", ".join(frappe.db.escape(st) for st in matching_step_types)
		conditions.append(f"`tabClearance Step`.step_type in ({escaped})")

	if not conditions:
		return "1=0"
	return "(" + " or ".join(conditions) + ")"
