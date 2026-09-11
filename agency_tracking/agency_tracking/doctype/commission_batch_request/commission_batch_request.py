# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE

import frappe
from frappe.model.document import Document
from frappe.utils import flt, today


class CommissionBatchRequest(Document):
	def validate(self):
		self._apply_settlement_math()
		self._set_title()

	def _set_title(self):
		"""'{Contractor} [{batch ID}]', e.g. 'Tihamat Asir Recruitment Company [CBR-2026-00021]' --
		so this batch reads as something other than a bare sequence number everywhere it shows up
		(list views, link fields, the invoice PDF, notifications). self.name is already assigned by
		the time validate() runs (autoname happens before the before_save hooks)."""
		self.title = f"{self.contractor} [{self.name}]" if self.contractor and self.name else self.name

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

	def write_off_totals(self):
		"""(original-currency, birr) summed across every write-off row -- a batch can have any
		number of write-offs (agency negotiates a discount more than once), not just one."""
		original = sum(flt(row.amount_original) for row in (self.write_offs or []))
		birr = sum(flt(row.amount_birr) for row in (self.write_offs or []))
		return original, birr

	def _apply_settlement_math(self):
		"""Single reconciled money model (2026-09-06: currency-native invoicing, audit N-1 follow-up;
		multi-write-off, 2026-09-06). Every batch is single-currency (items are grouped by currency
		at batch creation -- see finance_engine.create_batch_request), so the agency-facing numbers
		-- total, paid, write-off, balance due -- are all tracked in that ORIGINAL currency. That's
		what drives the invoice and the settlement status below. The parallel *_birr fields are
		recomputed alongside for internal income/expense accounting only; they never drive status.

		  obligation  = sum of non-Released item amounts (in the batch's currency)
		  accounted   = paid-per-item + sum(write-offs)
		  balance_due = obligation - accounted

		2026-09-07: advance_amount_original is NOT part of "accounted" -- an advance is a loan the
		agency requests ahead of time, not a payment against this batch's own obligation, so it no
		longer offsets balance_due or counts toward Settled/Partially Settled. It's still recorded
		on the batch (record_batch_advance) purely as a reference/history field, tracked but never
		netted against what's owed here.

		The settlement mechanisms that DO feed this one balance (per-item Paid marks and one-or-more
		write-offs) can't over-credit each other. Settled once accounted covers the obligation; any
		partial coverage on an open batch -> Partially Settled. Never downgrades an already-Settled
		batch."""
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

		write_off_original, write_off_birr = self.write_off_totals()
		self.write_off_total_original = write_off_original
		self.write_off_total_birr = write_off_birr
		paid_original, paid_birr = self.paid_from_items()
		self.paid_amount_original = paid_original
		self.paid_amount_birr = paid_birr

		accounted_original = paid_original + write_off_original
		self.balance_due_original = max(flt(self.total_amount_original) - accounted_original, 0)

		# Birr mirror, for internal accounting only. Each write-off's Birr amount is fixed at the
		# moment it's booked.
		accounted_birr = paid_birr + write_off_birr
		self.balance_due_birr = max(flt(self.total_amount_birr) - accounted_birr, 0)

		# 2026-09-11 fix (product decision): guard on "has this batch ever left Draft" rather than
		# "total_original > 0" -- a batch whose every remaining item got Released (carried into a
		# later batch via release_unpaid_items) has total_original = 0 too, which the old
		# `total_original > 0` guard treated identically to a fresh, empty Draft batch: neither
		# branch below ever fired, so status froze at "Partially Settled" forever (reproduced
		# live as CBR-00007: balance_due_original = 0.0, stuck, nothing left to actually collect).
		# accounted_original is always >= 0, so when total_original is 0 this condition is always
		# true -- correct, since "nothing left owed on THIS batch" is exactly what Settled should
		# mean here, whether that's because it was paid off, written off, or fully released
		# elsewhere. A fresh Draft batch (status still "Draft") is still excluded, so it can't
		# trivially read as Settled before it's ever been sent.
		if self.status != "Draft" and accounted_original >= total_original:
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
