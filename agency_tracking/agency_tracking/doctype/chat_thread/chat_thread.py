# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE

import frappe
from frappe.model.document import Document


class ChatThread(Document):
	def validate(self):
		if self.thread_type == "Agency":
			self.validate_agency_thread_shape()
		for row in self.participants:
			if row.user != "Administrator" and "Foreign Agency" in frappe.get_roles(row.user) and self.thread_type != "Agency":
				frappe.throw(
					"A Foreign Agency user can only be a participant in an Agency-type thread.",
					frappe.ValidationError,
				)

	def validate_agency_thread_shape(self):
		if not self.contractor:
			frappe.throw("An Agency thread must have a contractor.", frappe.ValidationError)
		if len(self.participants) != 2:
			frappe.throw(
				"An Agency thread has exactly two participants — the agency's user and their "
				"routed Communication Manager — never more (addendum-post-spec-refinements.md).",
				frappe.ValidationError,
			)
