# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class Placement(Document):
	def validate(self):
		self.stamp_departed_on()
		applicant = frappe.get_doc("Applicant", self.applicant)

		# Standard: only past CV Generated (portal-selected, Step 3). Muayena: Registered is
		# their terminal intake status (Part A.1 — they never touch CV Generated at all), so
		# Registered is the floor for their direct contract-upload entry (Step 4).
		valid_applicant_status = {
			"Standard": "CV Generated",
			"Muayena": "Registered",
		}[applicant.entry_track]
		if applicant.status != valid_applicant_status:
			frappe.throw(
				f"{applicant.name} ({applicant.entry_track}) must be '{valid_applicant_status}' "
				f"before a Placement can be created (currently '{applicant.status}').",
				frappe.ValidationError,
			)

		if applicant.active_placement and applicant.active_placement != self.name:
			frappe.throw(
				f"{applicant.name} already has an active Placement ({applicant.active_placement}).",
				frappe.ValidationError,
			)

		if self.destination_country != applicant.destination_country:
			frappe.throw(
				"Placement destination_country must match the Applicant's destination_country.",
				frappe.ValidationError,
			)

	def stamp_departed_on(self):
		if self.status == "Departed" and not self.departed_on:
			self.departed_on = now_datetime()
