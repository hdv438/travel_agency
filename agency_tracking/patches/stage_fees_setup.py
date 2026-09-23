# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# 2026-09-23 (client item #12): corridor known fees move from one combined ticketing entry to one
# auto-Approved Expense per fee, recorded when the fee's clearance step completes (stage_fees.py).
#   (a) give existing Corridor Known Fee rows a step_type (new required column), by fee type;
#   (b) placements whose fees were already handled the old way are flagged legacy_lump_fees, so
#       nothing is recorded twice: those with the combined ticketing entry (corridor_fees_logged=1)
#       and any already Ticketed/Departed (ticketed before 2026-09-19 known fees existed, when
#       stage costs were hand-logged);
#   (c) catch-up: every placement not yet ticketed gets fees for steps it already completed --
#       otherwise those would be recorded by neither the old system (never reached ticketing
#       under it) nor the new one (completed before it existed).
#   (a') a fee type that maps to a step this corridor doesn't have (Wakala: "Embassy" on Saudi,
#       "Kuwait Embassy" on Kuwait -- the first one that exists wins) -- the pre-09-23 corridors
#       carried every fee type, 0 for the ones that don't apply. Such a zero row is deleted (it
#       records nothing, and would otherwise make the corridor fail validation on its next save);
#       a NON-zero one is left without a step and logged to Error Log for someone to fix.
# Idempotent: re-running adds nothing.

import frappe
from frappe.utils import flt

STEP_TYPE_BY_FEE_TYPE = {
	"LMIS Fee": "LMIS Clearance",
	"Insurance Fee": "LMIS Clearance",
	"Taeshir Appointment Fee": "Taeshir",
	"Injaz Payment": "Taeshir",
	"Wakala Payment": ("Embassy", "Kuwait Embassy"),
	"Kuwait LMIS Fee": "Kuwait LMIS",
	# Police Ashara is tracked on the Kuwait LMIS step (clearance_step.json police_ashara_sec).
	"Police Ashara Fee": "Kuwait LMIS",
}


def execute():
	for corridor in frappe.get_all("Corridor Definition", pluck="name"):
		corridor_steps = set(
			frappe.get_all("Corridor Step", filters={"parent": corridor, "parenttype": "Corridor Definition"}, pluck="step_type")
		)
		for row in frappe.get_all(
			"Corridor Known Fee",
			filters={"parent": corridor, "parenttype": "Corridor Definition"},
			fields=["name", "fee_type", "step_type", "amount"],
		):
			if row.step_type in corridor_steps:
				continue
			candidates = STEP_TYPE_BY_FEE_TYPE.get(row.fee_type) or ()
			if isinstance(candidates, str):
				candidates = (candidates,)
			step_type = next((st for st in candidates if st in corridor_steps), None)
			if step_type:
				frappe.db.set_value("Corridor Known Fee", row.name, "step_type", step_type, update_modified=False)
			elif not flt(row.amount):
				frappe.db.delete("Corridor Known Fee", {"name": row.name})
			else:
				frappe.log_error(
					title="stage_fees_setup: fee has no step on its corridor",
					message=f"{corridor}: {row.fee_type} ({row.amount}) maps to none of {sorted(corridor_steps)} -- set its step by hand.",
				)

	frappe.db.sql(
		"""UPDATE `tabPlacement` SET legacy_lump_fees = 1
		WHERE legacy_lump_fees = 0 AND (corridor_fees_logged = 1 OR status IN ('Ticketed', 'Departed'))"""
	)
	frappe.db.commit()

	from agency_tracking.stage_fees import post_missing_stage_fees

	for placement_name in frappe.get_all(
		"Placement", filters={"legacy_lump_fees": 0, "status": ["in", ["Selected", "Processing", "Stamped"]]}, pluck="name"
	):
		post_missing_stage_fees(placement_name)
	frappe.db.commit()
