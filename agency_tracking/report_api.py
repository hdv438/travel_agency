# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Part I Step 13 / business-workflow-srs.md Part 8: "Management should be able to see, for any
# date range they choose... something anyone can pull up on demand for any custom date range —
# not a report someone has to manually assemble." Part F names get_financial_overview
# specifically as Admin-only; the rest are Manager/Admin ("management visibility").
#
# Built on top of Process Event (Step 6) wherever a pipeline-stage count is really "how many
# transitions of this kind happened in this window" — that's exactly what Process Event's
# reference_doctype/to_status/creation already record, so no new counters or duplicate logging
# were needed for CV-generated/selected/ticketed/departed counts. Only Clearance Step gained a
# genuinely new field this step (completed_by, above) because nothing already captured "who."

import frappe
from frappe.utils import getdate

MANAGEMENT_ROLES = {"Manager", "Admin", "Finance Manager", "System Manager"}


def _require_management():
	if not (MANAGEMENT_ROLES & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)


def _normalize_dates(from_date=None, to_date=None, **kwargs):
	from_date = from_date or kwargs.get("start_date") or kwargs.get("from") or frappe.utils.add_days(frappe.utils.today(), -30)
	to_date = to_date or kwargs.get("end_date") or kwargs.get("to") or frappe.utils.today()
	return str(from_date), str(to_date)


def _day_range(from_date, to_date):
	"""BETWEEN bounds for a Datetime column (generated_on, or the framework's own `creation`).
	A plain date string as the upper bound is interpreted as that day's midnight, silently
	excluding every same-day row with a nonzero time — caught by a same-day test asserting a
	backdated-to-10am row was actually counted."""
	return [f"{from_date} 00:00:00", f"{to_date} 23:59:59"]


def _transition_count(to_status, from_date, to_date, reference_doctype="Placement"):
	return frappe.db.count(
		"Process Event",
		filters={
			"reference_doctype": reference_doctype,
			"to_status": to_status,
			"creation": ["between", _day_range(from_date, to_date)],
		},
	)


@frappe.whitelist()
def get_daily_work_report(from_date=None, to_date=None, **kwargs):
	"""business-workflow-srs.md Part 8's exact list: CVs created, medicals processed,
	clearances issued, embassies cleared, tickets booked, departures confirmed."""
	_require_management()
	from_date, to_date = _normalize_dates(from_date, to_date, **kwargs)
	return {
		"from_date": from_date,
		"to_date": to_date,
		"cvs_created": frappe.db.count(
			"CV Record", filters={"docstatus": 1, "generated_on": ["between", _day_range(from_date, to_date)]}
		),
		"medicals_processed": frappe.db.count(
			"Applicant", filters={"medical_issue_date": ["between", [from_date, to_date]]}
		),
		"clearances_issued": frappe.db.count(
			"Clearance Step",
			filters={"status": ["in", ["Complete", "Issued"]], "date_completed": ["between", [from_date, to_date]]},
		),
		"embassies_cleared": frappe.db.count(
			"Clearance Step",
			filters={
				"step_type": ["in", ["Embassy", "Kuwait Embassy"]],
				"status": ["in", ["Stamped", "Complete"]],
				"date_completed": ["between", [from_date, to_date]],
			},
		),
		"tickets_booked": _transition_count("Ticketed", from_date, to_date),
		"departures_confirmed": _transition_count("Departed", from_date, to_date),
	}


@frappe.whitelist()
def get_staff_performance_report(from_date=None, to_date=None, **kwargs):
	""""The same breakdown per individual staff member — how much each person handled in a
	given period." Grouped by whoever actually did the work (CV Record.generated_by,
	Clearance Step.completed_by, Process Event.actor for placement-stage transitions) —
	deliberately not attempting to attribute "medicals processed" per staff member, since
	nothing in this build records who recorded a medical result; inventing an attribution here
	would be a guess dressed up as data.
	"""
	_require_management()
	from_date, to_date = _normalize_dates(from_date, to_date, **kwargs)

	performance = {}

	def _bucket(user):
		if user not in performance:
			performance[user] = {
				"user": user,
				"cvs_created": 0,
				"clearances_completed": 0,
				"tickets_booked": 0,
				"departures_confirmed": 0,
			}
		return performance[user]

	for row in frappe.get_all(
		"CV Record",
		filters={"docstatus": 1, "generated_on": ["between", _day_range(from_date, to_date)]},
		fields=["generated_by"],
	):
		if row.generated_by:
			_bucket(row.generated_by)["cvs_created"] += 1

	for row in frappe.get_all(
		"Clearance Step",
		filters={
			"status": ["in", ["Complete", "Issued", "Stamped"]],
			"date_completed": ["between", [from_date, to_date]],
		},
		fields=["completed_by"],
	):
		if row.completed_by:
			_bucket(row.completed_by)["clearances_completed"] += 1

	for row in frappe.get_all(
		"Process Event",
		filters={
			"reference_doctype": "Placement",
			"to_status": "Ticketed",
			"creation": ["between", _day_range(from_date, to_date)],
		},
		fields=["actor"],
	):
		if row.actor:
			_bucket(row.actor)["tickets_booked"] += 1

	for row in frappe.get_all(
		"Process Event",
		filters={
			"reference_doctype": "Placement",
			"to_status": "Departed",
			"creation": ["between", _day_range(from_date, to_date)],
		},
		fields=["actor"],
	):
		if row.actor:
			_bucket(row.actor)["departures_confirmed"] += 1

	return list(performance.values())


@frappe.whitelist()
def get_complaint_aging_report():
	"""business-workflow-srs.md Part 5: "how many are new, how many are still open and for how
	long, how many resolved" — "still open" (Unresolved) is explicitly meant to surface aging,
	not just a count, so each Unresolved complaint's age in days is returned individually
	(sorted oldest-first, same as list_unresolved_complaints) rather than collapsed into an
	average that would hide exactly the "forgotten at the bottom of the list" case the spec
	cares about.
	"""
	_require_management()

	unresolved = frappe.get_all(
		"Complaint", filters={"status": "Unresolved"}, fields=["name", "creation"], order_by="creation asc"
	)
	today = getdate()
	unresolved_with_age = [
		{"name": row.name, "age_days": (today - getdate(row.creation)).days} for row in unresolved
	]

	return {
		"new_count": frappe.db.count("Complaint", filters={"status": "New"}),
		"unresolved": unresolved_with_age,
		"resolved_count": frappe.db.count(
			"Complaint",
			filters={"status": ["in", ["Resolved", "Returned - Free Replacement Required", "Escalated", "Dismissed"]]},
		),
	}


@frappe.whitelist()
def get_financial_overview(from_date=None, to_date=None, **kwargs):
	"""Part F: "report_api.py gains get_financial_overview (Admin-only)" — deliberately not
	Manager, unlike every other report here (the financial visibility wall from Step 8 applies
	to reporting too, not just the raw ledger)."""
	_require_admin()
	from_date, to_date = _normalize_dates(from_date, to_date, **kwargs)

	base_filters = {"status": "Approved", "creation": ["between", _day_range(from_date, to_date)]}
	totals = {}
	for transaction_type in ("Commission", "Refund", "Income", "Expense"):
		rows = frappe.get_all(
			"Applicant Transaction",
			filters={**base_filters, "transaction_type": transaction_type},
			fields=["amount_birr"],
		)
		totals[transaction_type.lower()] = sum(r.amount_birr or 0 for r in rows)

	owed_rows = frappe.get_all(
		"Applicant Transaction",
		filters={"transaction_type": "Commission", "status": "Approved", "commission_batch_request": ["is", "not set"]},
		fields=["amount_birr"],
	)
	settled_batches = frappe.get_all(
		"Commission Batch Request",
		filters={"status": "Settled", "settled_on": ["between", [from_date, to_date]]},
		fields=["total_amount_birr"],
	)

	return {
		"from_date": from_date,
		"to_date": to_date,
		"totals_birr": totals,
		"outstanding_owed_birr": sum(r.amount_birr or 0 for r in owed_rows),
		"settled_in_period_birr": sum(r.total_amount_birr or 0 for r in settled_batches),
	}


def _require_admin():
	if not ({"Admin", "System Manager", "Finance Manager", "Manager"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)


@frappe.whitelist()
def get_pending_approval_queue():
	"""Admin-only (2026-08-29): every Pending Applicant Transaction, oldest-first -- so
	nothing sits forgotten waiting on Finance review, same shape as get_complaint_aging_report."""
	_require_admin()
	return frappe.get_all(
		"Applicant Transaction",
		filters={"status": "Pending"},
		fields=["name", "placement", "transaction_type", "amount_birr", "logged_by", "creation"],
		order_by="creation asc",
	)


@frappe.whitelist()
def get_cost_breakdown_report(from_date=None, to_date=None, **kwargs):
	"""Admin-only: Approved transaction totals grouped by destination_country and by the
	clearance step_type that generated the underlying Clearance Step Payment (where
	applicable) -- helps spot which corridor step is costing the most."""
	_require_admin()
	from_date, to_date = _normalize_dates(from_date, to_date, **kwargs)
	base_filters = {"status": "Approved", "creation": ["between", _day_range(from_date, to_date)]}

	by_country = {}
	for row in frappe.get_all(
		"Applicant Transaction",
		filters=base_filters,
		fields=["placement", "amount_birr", "transaction_type"],
	):
		if not row.placement:
			continue
		country = frappe.db.get_value("Placement", row.placement, "destination_country")
		if not country:
			continue
		by_country.setdefault(country, 0)
		by_country[country] += row.amount_birr or 0

	return {"from_date": from_date, "to_date": to_date, "by_country_birr": by_country}


@frappe.whitelist()
def get_employee_financial_report(from_date=None, to_date=None, **kwargs):
	"""Admin-only: per-employee net expense (expenses - income, Approved only) and
	approval/rejection rate on everything they submitted, side by side."""
	_require_admin()
	from_date, to_date = _normalize_dates(from_date, to_date, **kwargs)
	day_range = _day_range(from_date, to_date)

	net = {}
	for row in frappe.get_all(
		"Applicant Transaction",
		filters={"status": "Approved", "creation": ["between", day_range]},
		fields=["logged_by", "amount_birr", "transaction_type"],
	):
		if not row.logged_by:
			continue
		net.setdefault(row.logged_by, 0)
		if row.transaction_type == "Expense":
			net[row.logged_by] += row.amount_birr or 0
		elif row.transaction_type == "Income":
			net[row.logged_by] -= row.amount_birr or 0

	submitted_counts = {}
	approved_counts = {}
	for row in frappe.get_all(
		"Applicant Transaction",
		filters={"creation": ["between", day_range], "status": ["in", ["Approved", "Rejected"]]},
		fields=["logged_by", "status"],
	):
		if not row.logged_by:
			continue
		submitted_counts[row.logged_by] = submitted_counts.get(row.logged_by, 0) + 1
		if row.status == "Approved":
			approved_counts[row.logged_by] = approved_counts.get(row.logged_by, 0) + 1

	users = set(net) | set(submitted_counts)
	report = []
	for user in users:
		submitted = submitted_counts.get(user, 0)
		approved = approved_counts.get(user, 0)
		report.append(
			{
				"user": user,
				"net_expense_birr": net.get(user, 0),
				"submitted_count": submitted,
				"approval_rate": round(approved / submitted, 4) if submitted else None,
			}
		)
	return report


PLACEMENT_AGING_WARNING_DAYS = 25
PLACEMENT_AGING_CRITICAL_DAYS = 30


@frappe.whitelist()
def get_placement_aging_report():
	"""Admin/Manager: two buckets, both sorted worst-first (highest priority). Distinct from
	the existing contract_age_watchdog push notification -- this is a pull/list view, same
	pattern as get_complaint_aging_report."""
	MANAGEMENT_ROLES = {"Manager", "Admin"}
	if not (MANAGEMENT_ROLES & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)

	today = getdate()

	def _age_days(contract_signed_date):
		return (today - getdate(contract_signed_date)).days

	approaching_ticket_deadline = []
	for row in frappe.get_all(
		"Placement",
		filters={"status": ["not in", ["Ticketed", "Departed", "Cancelled"]], "contract_signed_date": ["is", "set"]},
		fields=["name", "contract_signed_date", "status"],
	):
		age = _age_days(row.contract_signed_date)
		if PLACEMENT_AGING_WARNING_DAYS <= age < PLACEMENT_AGING_CRITICAL_DAYS:
			approaching_ticket_deadline.append({"name": row.name, "age_days": age, "status": row.status})

	critical_not_departed = []
	for row in frappe.get_all(
		"Placement",
		filters={"status": ["not in", ["Departed", "Cancelled"]], "contract_signed_date": ["is", "set"]},
		fields=["name", "contract_signed_date", "status"],
	):
		age = _age_days(row.contract_signed_date)
		if age >= PLACEMENT_AGING_CRITICAL_DAYS:
			critical_not_departed.append({"name": row.name, "age_days": age, "status": row.status})

	approaching_ticket_deadline.sort(key=lambda r: r["age_days"], reverse=True)
	critical_not_departed.sort(key=lambda r: r["age_days"], reverse=True)

	return {
		"approaching_ticket_deadline": approaching_ticket_deadline,
		"critical_not_departed": critical_not_departed,
	}


@frappe.whitelist()
def get_operations_summary(from_date=None, to_date=None, **kwargs):
	"""Recruitment funnel + SLA/turnaround dashboard data (Manager/Admin), added on request
	from the frontend integration pass (2026-08-31) alongside list_applicants/list_placements
	(backend-issues #02). Funnel/stage counts are current-state snapshots (not time-boxed --
	a funnel describes where everything sits *right now*); conversion rates and turnaround
	times are computed from Process Event transitions that happened within from_date/to_date,
	same pattern as get_daily_work_report/_transition_count above. Pending/overdue reuses the
	same thresholds as get_placement_aging_report so the two never disagree."""
	_require_management()
	from_date, to_date = _normalize_dates(from_date, to_date, **kwargs)

	applicant_funnel = {
		status: frappe.db.count("Applicant", filters={"status": status})
		for status in ("Draft", "Registered", "CV Generated", "Cancelled")
	}
	placement_funnel = {
		status: frappe.db.count("Placement", filters={"status": status})
		for status in ("Selected", "Processing", "Stamped", "Ticketed", "Departed", "Cancelled")
	}

	registered_count = _transition_count("Registered", from_date, to_date, reference_doctype="Applicant")
	cv_generated_count = _transition_count("CV Generated", from_date, to_date, reference_doctype="Applicant")
	stamped_count = _transition_count("Stamped", from_date, to_date)
	ticketed_count = _transition_count("Ticketed", from_date, to_date)
	departed_count = _transition_count("Departed", from_date, to_date)

	def _rate(numerator, denominator):
		return round(numerator / denominator, 4) if denominator else None

	conversion_rates = {
		"registered_to_cv_generated": _rate(cv_generated_count, registered_count),
		"stamped_to_ticketed": _rate(ticketed_count, stamped_count),
		"ticketed_to_departed": _rate(departed_count, ticketed_count),
	}

	def _avg_turnaround_days(to_status, from_date, to_date):
		"""Mean days between a Placement's creation and its first reaching to_status, for
		every such transition recorded in the window -- a simple mean, not weighted/percentile;
		good enough for a dashboard tile, not a substitute for the underlying event list."""
		events = frappe.get_all(
			"Process Event",
			filters={
				"reference_doctype": "Placement",
				"to_status": to_status,
				"creation": ["between", _day_range(from_date, to_date)],
			},
			fields=["reference_name", "creation"],
		)
		if not events:
			return None
		durations = []
		for event in events:
			placement_creation = frappe.db.get_value("Placement", event.reference_name, "creation")
			if placement_creation:
				durations.append((frappe.utils.get_datetime(event.creation) - frappe.utils.get_datetime(placement_creation)).days)
		return round(sum(durations) / len(durations), 1) if durations else None

	turnaround_days = {
		"selected_to_ticketed": _avg_turnaround_days("Ticketed", from_date, to_date),
		"selected_to_departed": _avg_turnaround_days("Departed", from_date, to_date),
	}

	aging = get_placement_aging_report()
	pending_overdue = {
		"placements_approaching_ticket_deadline": len(aging["approaching_ticket_deadline"]),
		"placements_critical_not_departed": len(aging["critical_not_departed"]),
		"complaints_unresolved": frappe.db.count("Complaint", filters={"status": "Unresolved"}),
		"transactions_pending_approval": frappe.db.count("Applicant Transaction", filters={"status": "Pending"}),
	}

	return {
		"from_date": from_date,
		"to_date": to_date,
		"applicant_funnel": applicant_funnel,
		"placement_funnel": placement_funnel,
		"conversion_rates": conversion_rates,
		"turnaround_days": turnaround_days,
		"pending_overdue": pending_overdue,
	}


@frappe.whitelist()
def export_commissions_xlsx(contractor=None, destination_country=None, from_date=None, to_date=None):
	"""Generates and streams binary .xlsx (or CSV fallback) of unpaid / all commission records."""
	_require_management()

	filters = {"transaction_type": "Commission"}
	if contractor:
		placements = frappe.get_all("Placement", filters={"contractor": contractor}, pluck="name")
		if placements:
			filters["placement"] = ["in", placements]
		else:
			filters["placement"] = "non-existent"
	if from_date and to_date:
		filters["creation"] = ["between", _day_range(from_date, to_date)]

	rows = frappe.get_all(
		"Applicant Transaction",
		filters=filters,
		fields=["name", "placement", "applicant", "transaction_type", "amount_original", "currency_original", "amount_birr", "status", "creation"],
		order_by="creation desc"
	)

	# Try xlsxwriter first
	try:
		import io
		import xlsxwriter

		output = io.BytesIO()
		workbook = xlsxwriter.Workbook(output, {'in_memory': True})
		worksheet = workbook.add_worksheet("Commissions")

		header_format = workbook.add_format({'bold': True, 'bg_color': '#1E3A8A', 'font_color': '#FFFFFF', 'border': 1})
		cell_format = workbook.add_format({'border': 1})
		num_format = workbook.add_format({'border': 1, 'num_format': '#,##0.00'})

		headers = ["Transaction ID", "Placement", "Applicant", "Type", "Original Amount", "Currency", "ETB Amount", "Status", "Date"]
		for col, h in enumerate(headers):
			worksheet.write(0, col, h, header_format)
			worksheet.set_column(col, col, 18)

		for r_idx, r in enumerate(rows, start=1):
			worksheet.write(r_idx, 0, r.name, cell_format)
			worksheet.write(r_idx, 1, r.placement or "", cell_format)
			worksheet.write(r_idx, 2, r.applicant or "", cell_format)
			worksheet.write(r_idx, 3, r.transaction_type, cell_format)
			worksheet.write(r_idx, 4, float(r.amount_original or 0), num_format)
			worksheet.write(r_idx, 5, r.currency_original or "", cell_format)
			worksheet.write(r_idx, 6, float(r.amount_birr or 0), num_format)
			worksheet.write(r_idx, 7, r.status, cell_format)
			worksheet.write(r_idx, 8, str(r.creation)[:10], cell_format)

		workbook.close()
		output.seek(0)

		frappe.response['filename'] = f"commissions_report_{frappe.utils.today()}.xlsx"
		frappe.response['filecontent'] = output.getvalue()
		frappe.response['type'] = 'download'
		return
	except ImportError:
		pass

	# CSV fallback
	import csv
	import io
	output = io.StringIO()
	writer = csv.writer(output)
	writer.writerow(["Transaction ID", "Placement", "Applicant", "Type", "Original Amount", "Currency", "ETB Amount", "Status", "Date"])
	for r in rows:
		writer.writerow([r.name, r.placement or "", r.applicant or "", r.transaction_type, r.amount_original or 0, r.currency_original or "", r.amount_birr or 0, r.status, str(r.creation)[:10]])

	frappe.response['filename'] = f"commissions_report_{frappe.utils.today()}.csv"
	frappe.response['filecontent'] = output.getvalue()
	frappe.response['type'] = 'download'

