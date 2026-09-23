# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# 2026-09-22: Applicant Country Ban gained an `active` flag (lifting a ban now deactivates the
# row instead of frappe.delete_doc'ing it, preserving the ban/lift audit trail). Every row that
# existed before this change is, by definition, still an active ban -- nothing could have lifted
# one under the old hard-delete model and left a row behind. Direct frappe.db.set_value (not
# doc.save()) to avoid re-running validate()'s duplicate-active-ban check on every historical row
# just to fill in a default.

import frappe


def execute():
	frappe.db.set_value(
		"Applicant Country Ban",
		{"active": ["is", "not set"]},
		"active",
		1,
		update_modified=False,
	)
	frappe.db.commit()
