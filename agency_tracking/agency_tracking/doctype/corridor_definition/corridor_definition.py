# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE

import frappe
from frappe.model.document import Document
from frappe.utils import flt


class CorridorDefinition(Document):
	def validate(self):
		self.validate_unique_sequence_orders()
		self.validate_unique_step_types()
		self.validate_known_fees_single_currency()

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

	def validate_known_fees_single_currency(self):
		"""All known_fees rows get summed into ONE Applicant Transaction at ticketing time
		(corridor_engine.get_corridor_known_fees_total / placement_api.record_ticket_details) --
		that only makes sense if they're all the same currency. Zero-amount rows (a fee this
		corridor doesn't charge) are exempt -- their currency value is a required-field
		placeholder, not a real amount, so it shouldn't force every other row onto SAR/KWD/etc if
		the agency just left it at whatever the field defaults to."""
		currencies = {row.currency for row in (self.known_fees or []) if flt(row.amount)}
		if len(currencies) > 1:
			frappe.throw(
				f"Corridor {self.destination_country}: known_fees with a non-zero amount must all "
				f"share one currency (found {', '.join(sorted(currencies))}).",
				frappe.ValidationError,
			)
