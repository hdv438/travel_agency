# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE

import frappe
from frappe.model.document import Document


class CorridorDefinition(Document):
	def validate(self):
		self.validate_unique_sequence_orders()
		self.validate_unique_step_types()
		self.validate_known_fee_steps()

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

	def validate_known_fee_steps(self):
		"""Each known fee is recorded when its step_type completes (stage_fees.post_step_fees,
		2026-09-23), so that step has to exist on this corridor. Fees are recorded one row each,
		not summed, so rows may use different currencies (the old single-currency rule is gone)."""
		corridor_steps = {row.step_type for row in self.steps}
		for row in self.known_fees or []:
			if row.step_type not in corridor_steps:
				frappe.throw(
					f"Corridor {self.destination_country}: fee '{row.fee_type}' is set to record on "
					f"'{row.step_type}', which isn't one of this corridor's steps "
					f"({', '.join(sorted(corridor_steps)) or 'none'}).",
					frappe.ValidationError,
				)
