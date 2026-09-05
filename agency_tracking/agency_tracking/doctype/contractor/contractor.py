# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE

import frappe
from frappe.model.document import Document


class Contractor(Document):
	def validate(self):
		self.validate_user_has_foreign_agency_role()
		self.validate_communication_manager_role()

	def validate_user_has_foreign_agency_role(self):
		if self.user and "Foreign Agency" not in frappe.get_roles(self.user):
			frappe.throw(
				f"User {self.user} must have the 'Foreign Agency' role to be linked as a Contractor's portal user.",
				frappe.ValidationError,
			)

	def validate_communication_manager_role(self):
		if self.communication_manager and "Communication Manager" not in frappe.get_roles(self.communication_manager):
			frappe.throw(
				f"User {self.communication_manager} must have the 'Communication Manager' role.",
				frappe.ValidationError,
			)
