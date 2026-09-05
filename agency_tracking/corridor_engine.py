# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Part A.3: "no hard stops" — every function here reads Corridor Definition/Corridor Step data;
# none of them branch on a specific country name. Adding Dubai or Australia is purely a data
# change (a new Corridor Definition doc) — nothing in this module changes. Proven by
# test_corridor_engine.py inserting a throwaway corridor with no code changes and getting
# correct results back.

import frappe


@frappe.whitelist()
def get_corridor_steps(destination_country):
	"""Ordered step definitions for a destination country's corridor."""
	corridor_name = frappe.db.get_value(
		"Corridor Definition", {"destination_country": destination_country}, "name"
	)
	if not corridor_name:
		frappe.throw(f"No corridor configured for {destination_country}.", frappe.ValidationError)
	return frappe.get_all(
		"Corridor Step",
		filters={"parent": corridor_name},
		fields=["step_type", "is_mandatory", "sequence_order"],
		order_by="sequence_order asc",
	)


def get_first_step_type(destination_country):
	steps = get_corridor_steps(destination_country)
	return steps[0]["step_type"] if steps else None


def get_next_step_type(destination_country, current_sequence_order):
	"""The step_type immediately after current_sequence_order, or None if it was the last."""
	steps = get_corridor_steps(destination_country)
	remaining = [s for s in steps if s["sequence_order"] > current_sequence_order]
	return remaining[0]["step_type"] if remaining else None


def is_last_step(destination_country, sequence_order):
	steps = get_corridor_steps(destination_country)
	return bool(steps) and sequence_order == steps[-1]["sequence_order"]
