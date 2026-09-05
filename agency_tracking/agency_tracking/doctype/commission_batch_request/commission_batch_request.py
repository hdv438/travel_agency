# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE

import frappe
from frappe.model.document import Document
from frappe.utils import flt, today


class CommissionBatchRequest(Document):
	def validate(self):
		self._apply_settlement_math()

	def _txn_amount(self, transaction):
		return flt(frappe.db.get_value("Applicant Transaction", transaction, "amount_birr"))

	def paid_from_items(self):
		"""Birr already settled item-by-item (per-applicant marks). Excludes Released items."""
		return sum(
			self._txn_amount(row.transaction)
			for row in (self.items or [])
			if row.status == "Paid"
		)

	def _apply_settlement_math(self):
		"""Single reconciled money model (2026-09-05, audit N-1). All amounts are Birr (commissions
		are FX-normalized at accrual; the agency's foreign-currency payment is converted before it's
		recorded here).

		  obligation  = sum of non-Released item amounts
		  accounted   = paid-per-item + advance received + write-off (agreed discount)
		  balance_due = obligation - accounted

		The two settlement mechanisms (per-item Paid marks and batch-level advance/write-off) now
		feed ONE balance, so they can't over-credit each other. Settled once accounted covers the
		obligation; any partial coverage on an open batch -> Partially Settled. Never downgrades an
		already-Settled batch."""
		items = self.items or []
		# Released items were carried into a later batch -- no longer this batch's obligation.
		self.total_amount_birr = sum(
			self._txn_amount(row.transaction) for row in items if row.status != "Released"
		)

		advance = flt(self.advance_amount)
		write_off = flt(self.write_off_amount)
		paid_items = self.paid_from_items()
		total = flt(self.total_amount_birr)
		accounted = paid_items + advance + write_off
		self.balance_due_birr = max(total - accounted, 0)

		if total > 0 and accounted >= total:
			self.status = "Settled"
			if not self.settled_on:
				self.settled_on = today()
		elif self.status in ("Draft", "Sent") and accounted > 0:
			self.status = "Partially Settled"


def get_permission_query_conditions(user):
	"""Same wall as Applicant Transaction — a batch request is just as sensitive as the
	transactions it groups."""
	if not user:
		user = frappe.session.user
	if {"Finance Manager", "Admin"} & set(frappe.get_roles(user)):
		return ""
	return "1=0"
