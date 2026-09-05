# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE

from frappe.model.document import Document


class BankStatement(Document):
	def validate(self):
		if self.lines and all(row.match_status != "Unmatched" for row in self.lines):
			self.status = "Processed"
