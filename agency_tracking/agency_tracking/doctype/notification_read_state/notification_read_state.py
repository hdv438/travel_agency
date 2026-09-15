# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# One row per (user, alert_key) marking a live-computed notification (see
# agency_tracking.notification_feed) as Read or Dismissed for that user. Written exclusively
# server-side (ignore_permissions=True) by notification_api.mark_alerts_read /
# set_alert_state, both of which derive the user from frappe.session.user and never accept one
# as a parameter -- a user's own read state is nobody else's business, not even management's
# (contrast Background Job, where management legitimately needs oversight of everyone's jobs).

import frappe
from frappe.model.document import Document


class NotificationReadState(Document):
	pass


def get_permission_query_conditions(user):
	"""List-view scoping: every user sees only their own read-state rows. No management
	bypass here on purpose -- see module docstring."""
	if not user:
		user = frappe.session.user
	if user == "Administrator":
		return ""
	return f"`tabNotification Read State`.user = {frappe.db.escape(user)}"


def has_permission(doc, ptype=None, user=None):
	"""Single-document gate -- without this, get_permission_query_conditions above only
	filters list/report queries, and a role with blanket DocType-level read (System
	Manager/Admin per the JSON) could still reach another user's row by name via a raw
	frappe.get_doc()/REST call. Not even management gets a bypass here, matching the
	query-condition function above."""
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	return doc.get("user") == user


RETENTION_DAYS = 90


def cleanup_stale_read_state():
	"""hooks.py daily scheduler entry. Rows for a condition that has since resolved (e.g. a
	medical expiry that's now renewed, so that alert_key stops being generated) are harmless
	but accumulate forever with nothing else ever deleting them -- prune anything untouched for
	90+ days rather than letting the table grow unbounded."""
	from frappe.utils import add_days, today

	cutoff = add_days(today(), -RETENTION_DAYS)
	frappe.db.delete("Notification Read State", {"updated_at": ["<", cutoff]})
	frappe.db.commit()
