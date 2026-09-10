# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Tracks the async OCR/PDF jobs enqueued by agency_tracking.background_jobs.enqueue_job --
# written exclusively server-side (ignore_permissions=True); no role has create/write here.

import frappe
from frappe.model.document import Document

MANAGEMENT_ROLES = {"Admin", "Manager", "Administrator", "System Manager"}


class BackgroundJob(Document):
	pass


def get_permission_query_conditions(user):
	"""List-view scoping: management sees every job, everyone else sees only their own."""
	if not user:
		user = frappe.session.user
	if MANAGEMENT_ROLES & set(frappe.get_roles(user)):
		return ""
	return f"`tabBackground Job`.requested_by = {frappe.db.escape(user)}"


def has_permission(doc, ptype=None, user=None):
	"""Single-document read gate -- load-bearing for the result PDF's own permission check:
	a private File's download falls through to has_permission("read") on its attached_to_doctype
	(here, this Background Job), so without this a role with generic list-level read on
	Background Job could otherwise pull another user's Injaz/CV PDF by guessing the file URL."""
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	if doc.get("requested_by") == user:
		return True
	return bool(MANAGEMENT_ROLES & set(frappe.get_roles(user)))
