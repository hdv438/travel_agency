# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# "Ashara Teyezuwal": a permanent per-(Applicant, Country) blacklist. Checked in
# applicant_api.update_applicant whenever destination_country is set/changed -- see
# state_machine.check_country_ban_or_throw. Manual, judgment-call entries only (no automatic
# creation from any Complaint outcome), settable by Registrar/Complaint Manager/Manager/Admin.

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class ApplicantCountryBan(Document):
	def validate(self):
		if not self.set_by:
			self.set_by = frappe.session.user
		if not self.set_on:
			self.set_on = now_datetime()

		existing = frappe.db.get_value(
			self.doctype,
			{"applicant": self.applicant, "country": self.country, "name": ["!=", self.name or ""]},
			"name",
		)
		if existing:
			frappe.throw(
				f"{self.applicant} is already banned from {self.country} (see {existing}).",
				frappe.DuplicateEntryError,
			)
