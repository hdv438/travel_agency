# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE

import frappe
from frappe.model.document import Document


class Complaint(Document):
	def validate(self):
		if self.status == "Dismissed" and not self.resolution_notes:
			frappe.throw(
				"A written reason is required to dismiss a complaint (business-workflow-srs.md).",
				frappe.ValidationError,
			)
