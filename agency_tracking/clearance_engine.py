# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Part I Step 7: Clearance Step creation from Corridor Definition data, default assignment via
# Step Officer Mapping, and the LMIS -> Ticketing -> Departure auto-chain (Part A.2: "Officer
# holding LMIS is auto-assigned Ticketing and Departure-confirmation by default... reassignable
# by a manager if needed"). Registered into state_machine.TRANSITION_SIDE_EFFECTS at the bottom
# of this module — transition() calls these, nothing calls them directly except tests.

import frappe

from agency_tracking.corridor_engine import get_corridor_steps
from agency_tracking.notification_engine import notify
from agency_tracking.state_machine import TRANSITION_SIDE_EFFECTS

# Step types considered part of the "LMIS family" across corridors — matched by prefix rather
# than an exact-name list per corridor, consistent with Part A.3's "common step types are
# reusable across corridors" rather than each corridor needing bespoke handling.
LMIS_STEP_TYPE_PREFIX = "LMIS"


def assign_clearance_step(clearance_step_name, user):
	"""Create a ToDo for user against this Clearance Step, closing any existing open one first
	(reassignment — "reassignable by a manager if needed")."""
	open_todos = frappe.get_all(
		"ToDo",
		filters={"reference_type": "Clearance Step", "reference_name": clearance_step_name, "status": "Open"},
		pluck="name",
	)
	for todo_name in open_todos:
		frappe.db.set_value("ToDo", todo_name, "status", "Cancelled")

	frappe.get_doc(
		{
			"doctype": "ToDo",
			"reference_type": "Clearance Step",
			"reference_name": clearance_step_name,
			"allocated_to": user,
			"description": f"Clearance Step {clearance_step_name}",
			"status": "Open",
		}
	).insert(ignore_permissions=True)

	notify(user, "clearance_step_assigned", {"clearance_step": clearance_step_name})


def _broadcast_todo_to_role_holders(clearance_step_name, role):
	"""2026-08-29: for the six country+step roles, permission is role membership (see
	clearance_step.py's get_permission_query_conditions), not a single exclusive ToDo
	assignment -- so every holder gets their own open ToDo purely for the notification/queue
	UX, none of them "own" the row exclusively the way assign_clearance_step's single-officer
	model does. The two mechanisms never conflict because ToDo here is notification-only."""
	for user in frappe.get_all("Has Role", filters={"role": role}, pluck="parent"):
		frappe.get_doc(
			{
				"doctype": "ToDo",
				"reference_type": "Clearance Step",
				"reference_name": clearance_step_name,
				"allocated_to": user,
				"description": f"Clearance Step {clearance_step_name} ({role})",
				"status": "Open",
			}
		).insert(ignore_permissions=True)
		notify(user, "clearance_step_assigned", {"clearance_step": clearance_step_name})


def create_clearance_steps(placement, from_status=None):
	"""Placement enters Processing (Part A.2 Stage 5): materialize one Clearance Step per
	Corridor Step for this destination, in order. Notification routing: the six country+step
	roles (see clearance_step.CLEARANCE_ROLE_BY_STEP_TYPE) get a broadcast ToDo to every
	holder; anything else falls back to the legacy single Step Officer Mapping default_officer
	if one's configured."""
	from agency_tracking.agency_tracking.doctype.clearance_step.clearance_step import CLEARANCE_ROLE_BY_STEP_TYPE

	for step in get_corridor_steps(placement.destination_country):
		clearance_step = frappe.get_doc(
			{
				"doctype": "Clearance Step",
				"placement": placement.name,
				"step_type": step["step_type"],
				"sequence_order": step["sequence_order"],
				"is_mandatory": step["is_mandatory"],
				"status": "Pending",
			}
		).insert(ignore_permissions=True)

		role = CLEARANCE_ROLE_BY_STEP_TYPE.get(step["step_type"])
		if role:
			_broadcast_todo_to_role_holders(clearance_step.name, role)
			continue

		default_officer = frappe.db.get_value(
			"Step Officer Mapping", {"step_type": step["step_type"]}, "default_officer"
		)
		if default_officer:
			assign_clearance_step(clearance_step.name, default_officer)


def get_lmis_officer(placement):
	"""Whoever was (most recently) ToDo-assigned to this placement's LMIS-family Clearance
	Step. Deliberately not filtered to status="Open" — by the time this is consulted (Stamped/
	Ticketed, i.e. after Processing has finished), the LMIS step is normally already Complete
	and its ToDo Closed by clearance_api.complete_clearance_step(). "Officer holding LMIS" means
	whoever held it, not whoever currently has an open task for it.
	"""
	lmis_step = frappe.db.get_value(
		"Clearance Step",
		{"placement": placement.name, "step_type": ["like", f"{LMIS_STEP_TYPE_PREFIX}%"]},
		"name",
		order_by="sequence_order asc",
	)
	if not lmis_step:
		return None
	return frappe.db.get_value(
		"ToDo",
		{"reference_type": "Clearance Step", "reference_name": lmis_step},
		"allocated_to",
		order_by="creation desc",
	)


def _chain_todo_to_lmis_officer(placement, description):
	officer = get_lmis_officer(placement)
	if not officer:
		return
	frappe.get_doc(
		{
			"doctype": "ToDo",
			"reference_type": "Placement",
			"reference_name": placement.name,
			"allocated_to": officer,
			"description": description,
			"status": "Open",
		}
	).insert(ignore_permissions=True)
	notify(officer, "placement_todo_assigned", {"placement": placement.name, "description": description})


TICKETER_ROLE = "Ticketer"


def _placement_todo_to_role(placement, role, description):
	"""Broadcast a Placement-level ToDo + push to every holder of `role` -- the same
	notification/queue UX the six clearance roles get, but for a Placement task (ticketing /
	departure) rather than a Clearance Step."""
	for user in frappe.get_all("Has Role", filters={"role": role}, pluck="parent"):
		frappe.get_doc(
			{
				"doctype": "ToDo",
				"reference_type": "Placement",
				"reference_name": placement.name,
				"allocated_to": user,
				"description": description,
				"status": "Open",
			}
		).insert(ignore_permissions=True)
		notify(user, "placement_todo_assigned", {"placement": placement.name, "description": description})


def notify_ticketing_due(placement, from_status=None):
	"""Placement reached Stamped -> a ticket needs booking. Owned by the Ticketer(s); the LMIS
	officer who handled the case is also pinged for continuity (2026-09-05: was LMIS-only)."""
	description = f"Book ticket for Placement {placement.name}"
	_placement_todo_to_role(placement, TICKETER_ROLE, description)
	_chain_todo_to_lmis_officer(placement, description)


def notify_departure_due(placement, from_status=None):
	"""Placement reached Ticketed -> departure needs confirming. The Ticketer both books the ticket
	and confirms departure (2026-09-05: was the LMIS officer)."""
	_placement_todo_to_role(placement, TICKETER_ROLE, f"Confirm departure for Placement {placement.name}")


TRANSITION_SIDE_EFFECTS[("Placement", "Processing")] = create_clearance_steps
TRANSITION_SIDE_EFFECTS[("Placement", "Stamped")] = notify_ticketing_due
TRANSITION_SIDE_EFFECTS[("Placement", "Ticketed")] = notify_departure_due
