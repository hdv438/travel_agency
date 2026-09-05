# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE

import frappe
from frappe.model.document import Document


class ApplicantTransaction(Document):
	def validate(self):
		# Defense in depth: amount_birr must always be the product of the two figures that
		# produced it, regardless of which code path created this row.
		self.amount_birr = round((self.amount_original or 0) * (self.fx_rate or 0), 2)

		if self.placement and not self.cycle_number:
			self.cycle_number = frappe.db.get_value("Placement", self.placement, "cycle_number")

	def before_save(self):
		from agency_tracking.storage_engine import migrate_attach_to_r2

		applicant_name = self.applicant or (
			frappe.db.get_value("Placement", self.placement, "applicant") if self.placement else None
		)
		migrate_attach_to_r2(self, "receipt_image", "finance-receipts", applicant_name=applicant_name)


def get_permission_query_conditions(user):
	"""Part D + 2026-08-29: Finance Manager/Admin see every row (the full ledger). Everyone
	else who's allowed to log an entry (any internal staff role, per doctype-level create
	permission) can only see their *own* rows -- not "1=0 for everyone else" anymore, since
	that would make it impossible for staff to review what they themselves already submitted.
	"""
	if not user:
		user = frappe.session.user
	if {"Finance Manager", "Admin"} & set(frappe.get_roles(user)):
		return ""
	return f"`tabApplicant Transaction`.logged_by = {frappe.db.escape(user)}"
