# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE

import frappe
from frappe.model.document import Document
from frappe.utils import flt, today


class CommissionBatchRequest(Document):
	def validate(self):
		self._apply_settlement_math()

	def _txn_amounts(self, transaction):
		"""(original-currency amount, birr amount) for one batched commission transaction."""
		row = frappe.db.get_value(
			"Applicant Transaction", transaction, ["amount_original", "amount_birr"], as_dict=True
		)
		return flt(row.amount_original if row else 0), flt(row.amount_birr if row else 0)

	def paid_from_items(self):
		"""(original-currency, birr) already settled item-by-item (per-applicant marks). Excludes
		Released items."""
		original = birr = 0
		for row in self.items or []:
			if row.status != "Paid":
				continue
			o, b = self._txn_amounts(row.transaction)
			original += o
			birr += b
		return original, birr

	def _apply_settlement_math(self):
		"""Single reconciled money model (2026-09-06: currency-native invoicing, audit N-1 follow-up).
		Every batch is single-currency (items are grouped by currency at batch creation -- see
		finance_engine.create_batch_request), so the agency-facing numbers -- total, advance,
		write-off, balance due -- are all tracked in that ORIGINAL currency. That's what drives the
		invoice and the settlement status below. The parallel *_birr fields are recomputed alongside
		for internal income/expense accounting only; they never drive status.

		  obligation  = sum of non-Released item amounts (in the batch's currency)
		  accounted   = paid-per-item + advance received + write-off (agreed discount)
		  balance_due = obligation - accounted

		The two settlement mechanisms (per-item Paid marks and batch-level advance/write-off) feed
		ONE balance, so they can't over-credit each other. Settled once accounted covers the
		obligation; any partial coverage on an open batch -> Partially Settled. Never downgrades an
		already-Settled batch."""
		items = self.items or []
		# Released items were carried into a later batch -- no longer this batch's obligation.
		total_original = total_birr = 0
		for row in items:
			if row.status == "Released":
				continue
			o, b = self._txn_amounts(row.transaction)
			total_original += o
			total_birr += b
		self.total_amount_original = total_original
		self.total_amount_birr = total_birr

		advance_original = flt(self.advance_amount_original)
		write_off_original = flt(self.write_off_amount_original)
		paid_original, paid_birr = self.paid_from_items()

		accounted_original = paid_original + advance_original + write_off_original
		self.balance_due_original = max(flt(self.total_amount_original) - accounted_original, 0)

		# Birr mirrors, for internal accounting only. advance_amount/write_off_amount (Birr) are
		# fixed at the moment they're recorded (record_batch_advance / apply_batch_write_off), each
		# at that day's FX rate for the batch currency -- NOT re-derived here, so they don't drift
		# if the FX rate changes on a later re-save.
		accounted_birr = paid_birr + flt(self.advance_amount) + flt(self.write_off_amount)
		self.balance_due_birr = max(flt(self.total_amount_birr) - accounted_birr, 0)

		if total_original > 0 and accounted_original >= total_original:
			self.status = "Settled"
			if not self.settled_on:
				self.settled_on = today()
		elif self.status in ("Draft", "Sent") and accounted_original > 0:
			self.status = "Partially Settled"


def get_permission_query_conditions(user):
	"""Same wall as Applicant Transaction — a batch request is just as sensitive as the
	transactions it groups."""
	if not user:
		user = frappe.session.user
	if {"Finance Manager", "Admin"} & set(frappe.get_roles(user)):
		return ""
	return "1=0"
