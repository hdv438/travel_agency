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
# Idempotent: re-running adds nothing.

import frappe

STEP_TYPE_BY_FEE_TYPE = {
	"LMIS Fee": "LMIS Clearance",
	"Insurance Fee": "LMIS Clearance",
	"Taeshir Appointment Fee": "Taeshir",
	"Injaz Payment": "Taeshir",
	"Wakala Payment": "Embassy",
	"Kuwait LMIS Fee": "Kuwait LMIS",
	# Police Ashara is tracked on the Kuwait LMIS step (clearance_step.json police_ashara_sec).
	"Police Ashara Fee": "Kuwait LMIS",
}


def execute():
	for fee_type, step_type in STEP_TYPE_BY_FEE_TYPE.items():
		frappe.db.sql(
			"""UPDATE `tabCorridor Known Fee` SET step_type = %s
			WHERE fee_type = %s AND COALESCE(step_type, '') = ''""",
			(step_type, fee_type),
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
