# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE

import frappe

def execute():
	"""Ensure Administrator never has the Foreign Agency role or a linked Contractor,
	preventing role confusion and cross-tenant privilege bleeding."""
	if frappe.db.exists("Has Role", {"parent": "Administrator", "role": "Foreign Agency"}):
		frappe.db.delete("Has Role", {"parent": "Administrator", "role": "Foreign Agency"})
		frappe.db.commit()
		frappe.clear_cache(user="Administrator")

	# Unlink any Contractor accidentally assigned to Administrator
	contractors = frappe.get_all("Contractor", filters={"user": "Administrator"}, pluck="name")
	for c_name in contractors:
		frappe.db.set_value("Contractor", c_name, "user", None)
		frappe.db.commit()
