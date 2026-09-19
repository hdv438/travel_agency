# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# 2026-09-19: Complaint gained a computed `display_no` field ("#1", "#2", ... instead of
# CMP-00001 wherever a complaint is shown -- see complaint.py/_set_display_no) so agency/staff
# users never see the bare naming-series ID. That logic only runs in validate(), so existing rows
# need a one-time backfill; done with direct frappe.db.set_value (not doc.save()) to avoid
# re-running status/resolution validation on every historical complaint just to fill in a number.

import frappe


def execute():
	for complaint in frappe.get_all("Complaint", fields=["name", "display_no"]):
		if complaint.display_no:
			continue
		try:
			display_no = int(complaint.name.rsplit("-", 1)[-1])
		except ValueError:
			continue
		frappe.db.set_value("Complaint", complaint.name, "display_no", display_no, update_modified=False)

	frappe.db.commit()
