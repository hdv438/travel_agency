# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Audit N-10: the single Injaz fields on Clearance Step were replaced by the Injaz Attempt child
# table. Without this, a `bench migrate` on a site that already holds Taeshir/Injaz data would drop
# those columns and lose it. Runs in [pre_model_sync] (before the columns are dropped): it reads the
# legacy values via raw SQL, reloads the new doctypes, and re-creates them as one Active Injaz
# Attempt per step. No-op on a fresh install (columns never existed) or when there's nothing to move.

import frappe


def execute():
	if not frappe.db.has_column("Clearance Step", "injaz_application_id"):
		return  # fresh install / already migrated -- nothing to preserve

	rows = frappe.db.sql(
		"""
		select name, appointment_date, injaz_application_id, injaz_amount, injaz_payment_status,
		       injaz_paid_date, injaz_receipt_number, injaz_receipt_photo
		from `tabClearance Step`
		where step_type = 'Taeshir'
		  and (injaz_application_id is not null or appointment_date is not null
		       or injaz_amount is not null or injaz_receipt_number is not null)
		""",
		as_dict=True,
	)
	if not rows:
		return

	# Create the new Injaz Attempt table + the injaz_attempts field before writing child rows.
	frappe.reload_doc("agency_tracking", "doctype", "injaz_attempt")
	frappe.reload_doc("agency_tracking", "doctype", "clearance_step")

	for r in rows:
		step = frappe.get_doc("Clearance Step", r.name)
		if step.get("injaz_attempts"):
			continue  # already migrated
		step.append(
			"injaz_attempts",
			{
				"outcome": "Active",
				"appointment_date": r.appointment_date,
				"injaz_application_id": r.injaz_application_id,
				"injaz_amount": r.injaz_amount,
				"injaz_currency": "SAR",
				"payment_status": "Paid" if r.injaz_payment_status == "Paid" else "Unpaid",
				"paid_date": r.injaz_paid_date,
				"receipt_number": r.injaz_receipt_number,
				"receipt_photo": r.injaz_receipt_photo,
			},
		)
		step.save(ignore_permissions=True)

	frappe.db.commit()
