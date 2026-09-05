# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class CVRecord(Document):
	def validate(self):
		applicant = frappe.get_doc("Applicant", self.applicant)

		if applicant.entry_track != "Standard":
			frappe.throw(
				"CV Record does not apply to Muayena candidates (Part A.1) — "
				f"{applicant.name} is entry track '{applicant.entry_track}'.",
				frappe.ValidationError,
			)

		if applicant.status != "Registered":
			frappe.throw(
				f"Applicant {applicant.name} must be Registered before a CV can be generated "
				f"(currently '{applicant.status}').",
				frappe.ValidationError,
			)

	def before_insert(self):
		self.generated_on = now_datetime()
		self.generated_by = frappe.session.user
		self.cycle_number = frappe.db.get_value("Applicant", self.applicant, "cycle_number")
