# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE

import frappe
from frappe.model.document import Document


class FXRate(Document):
	def validate(self):
		existing = frappe.db.get_value(
			"FX Rate",
			{"currency": self.currency, "rate_date": self.rate_date, "name": ["!=", self.name or ""]},
			"name",
		)
		if existing:
			frappe.throw(
				f"An FX Rate for {self.currency} on {self.rate_date} already exists ({existing}).",
				frappe.DuplicateEntryError,
			)
