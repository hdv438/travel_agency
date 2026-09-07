# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# 2026-09-07: Commission Batch Request and Clearance Step gained a computed `title` field
# ("{Contractor} [{batch ID}]" / "{Step Type} — {Applicant} [{step ID}]") so these records read
# as something other than a bare sequence number in lists, link fields, invoices, and
# notifications -- see commission_batch_request.py/_set_title and clearance_step.py/_set_title.
# That logic only runs in validate(), so existing rows need a one-time backfill; done with direct
# frappe.db.set_value (not doc.save()) to avoid re-running settlement math / status transitions
# on every historical record just to fill in a label.

import frappe


def execute():
	for batch in frappe.get_all("Commission Batch Request", fields=["name", "contractor", "title"]):
		if batch.title:
			continue
		title = f"{batch.contractor} [{batch.name}]" if batch.contractor else batch.name
		frappe.db.set_value("Commission Batch Request", batch.name, "title", title, update_modified=False)

	steps = frappe.get_all("Clearance Step", fields=["name", "step_type", "placement", "title"])
	placement_applicant = {}
	applicant_full_name = {}
	for step in steps:
		if step.title or not step.placement:
			continue
		if step.placement not in placement_applicant:
			placement_applicant[step.placement] = frappe.db.get_value("Placement", step.placement, "applicant")
		applicant_name = placement_applicant[step.placement]
		if not applicant_name:
			continue
		if applicant_name not in applicant_full_name:
			applicant_full_name[applicant_name] = frappe.db.get_value("Applicant", applicant_name, "full_name")
		full_name = applicant_full_name[applicant_name]
		if not full_name:
			continue
		title = f"{step.step_type} — {full_name} [{step.name}]"
		frappe.db.set_value("Clearance Step", step.name, "title", title, update_modified=False)

	frappe.db.commit()
