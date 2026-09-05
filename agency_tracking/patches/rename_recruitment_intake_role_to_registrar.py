# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# The Part G "Recruitment/Intake" role was renamed to "Registrar" (same scope: owns the
# Applicant from Draft through CV Generated). Rebuild-in-place: the live site already has the
# old Role record and, potentially, users assigned to it, so migrate must carry those over
# before doctype sync applies the new (Registrar-referencing) DocPerm rows. Runs pre_model_sync
# so "Registrar" exists by the time the Applicant/CV Record/Process Event JSONs are synced.

import frappe

OLD = "Recruitment/Intake"
NEW = "Registrar"


def execute():
	if not frappe.db.exists("Role", OLD):
		# Fresh site or already migrated — install.create_roles() / doctype sync ensures NEW exists.
		return

	if not frappe.db.exists("Role", NEW):
		frappe.get_doc({"doctype": "Role", "role_name": NEW, "desk_access": 1}).insert(
			ignore_permissions=True
		)

	# Preserve user assignments: give every user who had the old role the new one.
	for user in set(frappe.get_all("Has Role", filters={"role": OLD}, pluck="parent")):
		if frappe.db.exists("User", user) and not frappe.db.exists(
			"Has Role", {"parent": user, "role": NEW}
		):
			frappe.get_doc("User", user).add_roles(NEW)

	# Drop the old role and its now-stale assignments; the old DocPerm rows fall away when the
	# doctype JSONs (no longer referencing OLD) are synced later in this same migrate.
	frappe.db.delete("Has Role", {"role": OLD})
	frappe.delete_doc("Role", OLD, ignore_permissions=True, force=True)
	frappe.db.commit()
