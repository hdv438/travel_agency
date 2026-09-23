# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# "Ashara Teyezuwal": a permanent per-(Applicant, Country) blacklist. Checked in
# applicant_api._check_country_ban_or_throw, called from update_applicant (on a destination_country
# change), register_applicant, cv_api.generate_cv, restart_applicant, and as a
# backstop in portal_api.select_candidate; portal_api.list_portal_candidates also filters banned
# applicants out of the marketplace listing. Manual, judgment-call entries only (no automatic
# creation from any Complaint outcome), settable by Registrar/Complaint Manager/Manager/Admin.
#
# Lifting a ban (applicant_api.remove_country_ban) deactivates the row (active=0, lifted_* stamped)
# rather than deleting it, so the ban/lift history stays auditable -- only active=1 rows block
# anything or count toward the duplicate-entry check below.

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class ApplicantCountryBan(Document):
	def validate(self):
		if not self.set_by:
			self.set_by = frappe.session.user
		if not self.set_on:
			self.set_on = now_datetime()
		if self.active is None:
			self.active = 1

		if self.active:
			existing = frappe.db.get_value(
				self.doctype,
				{
					"applicant": self.applicant,
					"country": self.country,
					"active": 1,
					"name": ["!=", self.name or ""],
				},
				"name",
			)
			if existing:
				frappe.throw(
					f"{self.applicant} is already banned from {self.country} (see {existing}).",
					frappe.DuplicateEntryError,
				)
