# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Part A.3: "no hard stops" — every function here reads Corridor Definition/Corridor Step data;
# none of them branch on a specific country name. Adding Dubai or Australia is purely a data
# change (a new Corridor Definition doc) — nothing in this module changes. Proven by
# test_corridor_engine.py inserting a throwaway corridor with no code changes and getting
# correct results back.

import frappe
from frappe.utils import flt


@frappe.whitelist()
def get_corridor_steps(destination_country=None, **kwargs):
	"""Ordered step definitions for a destination country's corridor."""
	if not destination_country:
		frappe.throw("destination_country is required.", frappe.ValidationError)
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


def get_corridor_known_fees_total(destination_country):
	"""(total_amount, currency) across every known_fees row configured for this corridor (LMIS,
	Insurance, Taeshir, Injaz, Wakala, Kuwait LMIS, Police Ashara) -- summed into a single
	ticketing-time Expense by placement_api.record_ticket_details, replacing the old per-stage
	manual income/expense logging (2026-09-19, product decision). Returns (0, None) when the
	corridor has no known_fees rows at all -- distinct from "rows exist but total to 0" (which
	returns whatever currency the rows declared, even though the number is 0), so a caller can
	tell "nothing configured" apart from "configured at zero"."""
	if not destination_country:
		return 0, None
	corridor_name = frappe.db.get_value(
		"Corridor Definition", {"destination_country": destination_country}, "name"
	)
	if not corridor_name:
		return 0, None
	rows = frappe.get_all(
		"Corridor Known Fee", filters={"parent": corridor_name}, fields=["amount", "currency"]
	)
	if not rows:
		return 0, None
	total = sum(flt(row.amount) for row in rows)
	# CorridorDefinition.validate_known_fees_single_currency already enforces this at save time
	# for non-zero rows -- this just picks a currency to report against `total`, preferring one
	# that's actually attached to money rather than a zero row's placeholder value.
	currency = next((row.currency for row in rows if flt(row.amount)), rows[0].currency)
	return total, currency
