# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE

import frappe


def execute():
	"""Sets idle session expiry to 24 hours ('24:00') in System Settings."""
	try:
		settings = frappe.get_doc("System Settings")
		settings.session_expiry = "24:00"
		settings.flags.ignore_mandatory = True
		settings.save(ignore_permissions=True)
	except Exception:
		frappe.db.set_single_value("System Settings", "session_expiry", "24:00")
		frappe.defaults.set_global_default("session_expiry", "24:00")
	frappe.db.commit()
