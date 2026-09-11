# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Immutable audit trail (Part B) — written by state_machine.transition() and
# finance_api.void_transaction(), never edited directly. See "Activity visibility" in
# addendum-post-spec-refinements.md for the query conditions below (Finance Manager's
# "Applicant Transaction"-only scoping is now live as of Step 8; Complaint Manager's own
# scoping is still inert until Step 10 creates the Complaint doctype).

import frappe
from frappe.model.document import Document

EVENTS_REQUIRING_REMARKS = {"Override", "Voided"}


class ProcessEvent(Document):
	def validate(self):
		if self.event_type in EVENTS_REQUIRING_REMARKS and not self.remarks:
			frappe.throw(
				f"A written reason is required for a {self.event_type} event.", frappe.ValidationError
			)


def get_permission_query_conditions(user):
	if not user:
		user = frappe.session.user
	roles = set(frappe.get_roles(user))
	if {"Admin", "Manager"} & roles:
		return ""
	if "Finance Manager" in roles:
		return "`tabProcess Event`.reference_doctype in ('Applicant Transaction', 'Commission Batch Request', 'Contractor')"
	return f"`tabProcess Event`.actor = {frappe.db.escape(user)}"


def has_permission(doc, ptype=None, user=None):
	"""Single-document mirror of get_permission_query_conditions above (2026-09-11, same class
	of gap found and fixed for Clearance Step/Background Job earlier this session): that hook
	only filters list/report queries, never a single frappe.get_doc()/REST call -- without this,
	every role with blanket DocType-level read (Registrar, Clearance Officer, Ticketer,
	Complaint Manager, per process_event.json) could read ANY Process Event by name, including
	other users' audit-trail actions, despite being restricted to their own actor rows in every
	list view."""
	user = user or frappe.session.user
	if not doc or not doc.get("name"):
		return True
	roles = set(frappe.get_roles(user))
	if {"Admin", "Manager"} & roles:
		return True
	if "Finance Manager" in roles:
		return doc.get("reference_doctype") in ("Applicant Transaction", "Commission Batch Request", "Contractor")
	return doc.get("actor") == user
