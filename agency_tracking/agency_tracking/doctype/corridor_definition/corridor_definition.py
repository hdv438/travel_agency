# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE

import frappe
from frappe.model.document import Document


class CorridorDefinition(Document):
	def validate(self):
		self.validate_unique_sequence_orders()
		self.validate_unique_step_types()

	def validate_unique_sequence_orders(self):
		orders = [row.sequence_order for row in self.steps]
		if len(orders) != len(set(orders)):
			frappe.throw(
				f"Corridor {self.destination_country}: sequence_order values must be unique across steps.",
				frappe.ValidationError,
			)

	def validate_unique_step_types(self):
		step_types = [row.step_type for row in self.steps]
		if len(step_types) != len(set(step_types)):
			frappe.throw(
				f"Corridor {self.destination_country}: step_type values must be unique across steps.",
				frappe.ValidationError,
			)
