# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# 2026-09-06: Commission Batch Request's single write_off_amount_original/write_off_amount/
# write_off_reason/write_off_transaction fields were replaced by a Commission Batch Write Off
# child table (write_offs), so a batch can record more than one negotiated discount instead of
# just one. Without this, a `bench migrate` on a site that already recorded a write-off under the
# old single-field schema would drop those columns and lose it. Runs in [pre_model_sync] (before
# the columns are dropped): reads the legacy values via raw SQL, reloads the new child doctype +
# parent doctype, and re-creates each as one row in write_offs. No-op on a fresh install (columns
# never existed) or when there's nothing to move.

import frappe


def execute():
	if not frappe.db.has_column("Commission Batch Request", "write_off_amount_original"):
		return  # fresh install / already migrated -- nothing to preserve

	rows = frappe.db.sql(
		"""
		select name, write_off_amount_original, write_off_amount, write_off_reason, write_off_transaction
		from `tabCommission Batch Request`
		where write_off_amount_original is not null and write_off_amount_original > 0
		""",
		as_dict=True,
	)
	if not rows:
		return

	frappe.reload_doc("agency_tracking", "doctype", "commission_batch_write_off")
	frappe.reload_doc("agency_tracking", "doctype", "commission_batch_request")

	for r in rows:
		batch = frappe.get_doc("Commission Batch Request", r.name)
		if batch.get("write_offs"):
			continue  # already migrated
		batch.append(
			"write_offs",
			{
				"amount_original": r.write_off_amount_original,
				"amount_birr": r.write_off_amount,
				"reason": r.write_off_reason or "Migrated from single write-off field",
				"transaction": r.write_off_transaction,
				"write_off_date": frappe.utils.today(),
			},
		)
		batch.save(ignore_permissions=True)

	frappe.db.commit()
