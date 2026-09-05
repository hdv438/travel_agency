# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Part F: module-scoped whitelisted functions, no raw /api/resource/* exposure.

import frappe

from agency_tracking.notification_engine import (
	ensure_vapid_keys,
	generate_vapid_keys as _generate_vapid_keys,
	register_push_subscription as _register_push_subscription,
)
from agency_tracking.watchdogs import send_wakala_reminder


@frappe.whitelist()
def subscribe_to_push(endpoint, p256dh, auth):
	"""A user subscribing their own browser — never on behalf of anyone else."""
	_register_push_subscription(frappe.session.user, endpoint, p256dh, auth)
	return {"status": "subscribed"}


@frappe.whitelist()
def get_vapid_public_key():
	"""Frontend fetches the VAPID application server key to pass to PushManager.subscribe().
	Auto-provisions the keypair on first call so push works out of the box (see
	notification_engine.ensure_vapid_keys). Safe for any authenticated user -- the public key
	is, by design, public."""
	config = ensure_vapid_keys()
	return {"vapid_public_key": config.vapid_public_key}


@frappe.whitelist()
def regenerate_vapid_keys():
	"""Admin-only: force a brand-new VAPID keypair (e.g. after a suspected key leak). NOTE: this
	invalidates every existing Push Subscription -- browsers subscribed under the old key will
	stop receiving pushes until they re-subscribe with the new applicationServerKey. Returns the
	new public key."""
	frappe.only_for(("System Manager", "Administrator"))
	public_key, private_pem = _generate_vapid_keys()
	config = frappe.get_single("Notification Config")
	config.vapid_public_key = public_key
	config.vapid_private_key = private_pem
	if not config.vapid_claims_email:
		site = frappe.local.site if getattr(frappe.local, "site", None) else "localhost"
		config.vapid_claims_email = f"admin@{site}"
	config.save(ignore_permissions=True)
	return {"vapid_public_key": public_key, "message": "VAPID keys regenerated. Existing subscriptions must re-subscribe."}


@frappe.whitelist()
def trigger_wakala_reminder(clearance_step_name=None, **kwargs):
	"""business-workflow-srs.md: "plus staff can trigger a reminder manually any time" — the
	escape hatch alongside the automatic Fri/Sat/Sun watchdog."""
	clearance_step_name = clearance_step_name or kwargs.get("name") or kwargs.get("clearance_step")
	if not clearance_step_name:
		clearance_step_name = frappe.db.get_value("Clearance Step", {"step_type": ["in", ["Embassy", "Kuwait Embassy"]]}, "name")
	if not clearance_step_name:
		frappe.throw("clearance_step_name is required.", frappe.ValidationError)
	step = frappe.get_doc("Clearance Step", clearance_step_name)
	if step.step_type not in ("Embassy", "Kuwait Embassy"):
		frappe.throw("This is only meaningful for an Embassy clearance step.", frappe.ValidationError)
	if not step.has_permission("read"):
		frappe.throw("Not permitted.", frappe.PermissionError)
	send_wakala_reminder(clearance_step_name, step.placement)
	return {"status": "reminder sent"}


@frappe.whitelist(allow_guest=False)
def get_push_subscription_status():
	"""Read-only -- tells the frontend whether the current user already has an active Push
	Subscription, so it knows whether to show the manual \"enable notifications\" fallback
	button (needed when the browser's own permission prompt is auto-dismissed or the user
	cancels it without realizing)."""
	return {
		"subscribed": bool(
			frappe.db.exists("Push Subscription", {"user": frappe.session.user})
		)
	}
