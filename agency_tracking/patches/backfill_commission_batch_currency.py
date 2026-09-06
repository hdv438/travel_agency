# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# 2026-09-06: Commission Batch Request gained currency-native fields (currency,
# total_amount_original, advance_amount_original, balance_due_original, plus the write_offs child
# table -- see migrate_commission_batch_write_off_to_child_table.py, which runs first in
# pre_model_sync and handles any legacy single write-off) so invoices are denominated in
# USD/SAR/etc instead of always Birr. Existing batches predate this and need `currency` +
# `total_amount_original` backfilled from their items (all items are the same currency in
# practice, since a batch groups one contractor+country's rate-table currency -- but batching
# never enforced that before this change, so mixed batches are flagged rather than guessed at).
#
# advance_amount_original can only be safely reverse-derived for ETB batches (Birr IS the
# original currency there, 1:1). For non-ETB batches that already recorded an advance in Birr,
# there's no stored historical FX rate to invert -- that's left at 0 and logged for a Finance
# Manager to re-enter in the batch's currency.

import frappe


def execute():
	if not frappe.db.has_column("Commission Batch Request", "currency"):
		return  # fresh install -- doctype sync already includes the new fields

	batch_names = frappe.get_all("Commission Batch Request", pluck="name")
	for batch_name in batch_names:
		batch = frappe.get_doc("Commission Batch Request", batch_name)
		if batch.currency:
			continue  # already backfilled (or created post-migration)

		currencies = set()
		for row in batch.items:
			if row.status == "Released":
				continue
			currency = frappe.db.get_value("Applicant Transaction", row.transaction, "currency_original")
			if currency:
				currencies.add(currency)

		if len(currencies) > 1:
			frappe.log_error(
				title="backfill_commission_batch_currency: mixed-currency batch",
				message=(
					f"{batch_name} has items in multiple currencies ({', '.join(sorted(currencies))}) "
					"from before batching enforced a single currency. Left uncurrencied -- needs manual "
					"review/split by a Finance Manager."
				),
			)
			continue

		batch.currency = currencies.pop() if currencies else "ETB"

		if batch.currency == "ETB":
			# Birr IS the original currency here -- safe 1:1 backfill.
			batch.advance_amount_original = batch.advance_amount or 0
		elif batch.advance_amount:
			frappe.log_error(
				title="backfill_commission_batch_currency: unrecoverable advance",
				message=(
					f"{batch_name} ({batch.currency}) has advance_amount={batch.advance_amount} recorded "
					"in Birr with no stored historical FX rate to invert. Left at 0 in the new "
					f"currency-native field -- a Finance Manager should re-enter this in {batch.currency} "
					"if the batch is still open."
				),
			)

		batch.save(ignore_permissions=True)

	frappe.db.commit()
