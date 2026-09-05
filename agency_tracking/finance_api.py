# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Part F: module-scoped whitelisted functions, no raw /api/resource/* exposure.

import frappe
from frappe.utils import flt, now, today

from agency_tracking.finance_engine import (
	accrue_commission,
	apply_batch_write_off,
	create_batch_request,
	fetch_daily_fx_rates,
	get_fx_rate as _get_fx_rate,
	list_owed_commissions,
	mark_batch_items_paid,
	match_batch_payment_proof,
	record_fx_rate,
	release_unpaid_items as _release_unpaid_items,
	render_batch_invoice_pdf,
	settle_batch_request,
)
from agency_tracking.roles import INTERNAL_STAFF_ROLES
from agency_tracking.state_machine import log_action, transition
from decimal import Decimal


def _log_stage_transaction(
	transaction_type,
	amount,
	currency,
	description,
	placement_name=None,
	stage_logged_at=None,
	applicant=None,
	stage=None,
):
	"""2026-08-29: open to any internal staff role, no longer gated on being assigned to the
	placement's current stage — Finance Manager/Admin approval (approve_transaction/
	reject_transaction) is the real gate now, so the write side can be permissive."""
	if not (INTERNAL_STAFF_ROLES & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)

	placement = frappe.get_doc("Placement", placement_name) if placement_name else None
	if not applicant and placement:
		applicant = placement.applicant
	elif applicant and not placement:
		active_placement = frappe.db.get_value("Applicant", applicant, "active_placement")
		if active_placement:
			placement_name = active_placement
			placement = frappe.get_doc("Placement", placement_name)

	stage_value = stage or stage_logged_at
	if not stage_value:
		if placement:
			stage_value = placement.status
		elif applicant:
			stage_value = frappe.db.get_value("Applicant", applicant, "status")

	fx_rate, fx_rate_date = _get_fx_rate(currency)
	txn = frappe.get_doc(
		{
			"doctype": "Applicant Transaction",
			"applicant": applicant,
			"placement": placement_name,
			"transaction_type": transaction_type,
			"amount_original": Decimal(str(amount)),
			"currency_original": currency,
			"fx_rate": Decimal(str(fx_rate)),
			"fx_rate_date": fx_rate_date,
			"amount_birr": round(Decimal(str(amount)) * Decimal(str(fx_rate)), 2),
			"description": description,
			"stage_logged_at": stage_value,
			"logged_by": frappe.session.user,
		}
	).insert(ignore_permissions=True)
	return txn.as_dict()


@frappe.whitelist()
def log_stage_expense(amount=None, currency=None, description=None, placement=None, applicant=None, stage=None, stage_logged_at=None, **kwargs):
	amount = amount or kwargs.get("amount_original") or kwargs.get("amount_birr")
	currency = currency or kwargs.get("currency_original") or "ETB"
	description = description or kwargs.get("reference_text") or kwargs.get("remarks") or "Expense"
	placement = placement or kwargs.get("placement_name")
	applicant = applicant or kwargs.get("applicant_name")
	return _log_stage_transaction(
		"Expense",
		amount,
		currency,
		description,
		placement_name=placement,
		stage_logged_at=stage_logged_at,
		applicant=applicant,
		stage=stage,
	)


@frappe.whitelist()
def log_stage_income(amount=None, currency=None, description=None, placement=None, applicant=None, stage=None, stage_logged_at=None, **kwargs):
	amount = amount or kwargs.get("amount_original") or kwargs.get("amount_birr")
	currency = currency or kwargs.get("currency_original") or "ETB"
	description = description or kwargs.get("reference_text") or kwargs.get("remarks") or "Income"
	placement = placement or kwargs.get("placement_name")
	applicant = applicant or kwargs.get("applicant_name")
	return _log_stage_transaction(
		"Income",
		amount,
		currency,
		description,
		placement_name=placement,
		stage_logged_at=stage_logged_at,
		applicant=applicant,
		stage=stage,
	)


@frappe.whitelist()
def approve_transaction(transaction_name):
	"""Finance Manager/Admin only. Moves Pending -> Approved via the sanctioned transition()
	path -- only Approved entries count toward ledger/balance totals (Part D)."""
	if not ({"Finance Manager", "Admin"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)

	txn = frappe.get_doc("Applicant Transaction", transaction_name)
	txn.approved_by = frappe.session.user
	txn.approved_on = now()
	transition(txn, "Approved")
	return txn.as_dict()


@frappe.whitelist()
def reject_transaction(transaction_name, rejection_reason):
	"""Finance Manager/Admin only, mandatory reason. Pending -> Rejected; never counts toward
	the ledger."""
	if not ({"Finance Manager", "Admin"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	if not rejection_reason:
		frappe.throw("A reason is required to reject a transaction.", frappe.ValidationError)

	txn = frappe.get_doc("Applicant Transaction", transaction_name)
	txn.rejection_reason = rejection_reason
	transition(txn, "Rejected", remarks=rejection_reason)
	return txn.as_dict()


@frappe.whitelist()
def void_transaction(transaction_name, void_reason):
	"""No hard delete, ever (addendum). Finance Manager/Admin only, mandatory reason. Only
	legal from Approved (ALLOWED_TRANSITIONS enforces this — transition() itself rejects
	voiding a Pending/Rejected row). Routed through transition() like every other status
	change (never doc.status = X; doc.save() directly) -- the row stays visible with its
	status flagged and a Process Event on the audit trail, never disappears."""
	if not ({"Finance Manager", "Admin"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	if not void_reason:
		frappe.throw("A reason is required to void a transaction.", frappe.ValidationError)

	txn = frappe.get_doc("Applicant Transaction", transaction_name)
	transition(txn, "Voided", remarks=void_reason)
	return txn.as_dict()


@frappe.whitelist()
def trigger_early_commission_accrual(placement_name):
	"""Part D: "Manual early-trigger (idempotency-guarded either way)" — for cases needing to
	bill sooner than Departed. Same accrue_commission() as the automatic path, so calling this
	and then later reaching Departed naturally is a no-op the second time."""
	if not ({"Finance Manager", "Admin", "Manager"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	placement = frappe.get_doc("Placement", placement_name)
	txn = accrue_commission(placement)
	if txn is None:
		frappe.throw(f"{placement_name} already has an active commission transaction.", frappe.ValidationError)
	return txn.as_dict()


@frappe.whitelist()
def get_fx_rate(currency, as_of_date=None):
	if not ({"Finance Manager", "Admin", "System Manager"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	rate, rate_date = _get_fx_rate(currency, as_of_date)
	return {"currency": currency, "rate_to_birr": rate, "rate_date": rate_date}


@frappe.whitelist()
def set_fx_rate(currency, rate_to_birr=None, rate_date=None, **kwargs):
	if not ({"Finance Manager", "Admin", "System Manager"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	rate = rate_to_birr or kwargs.get("rate_to_etb") or kwargs.get("rate")
	if not rate:
		frappe.throw("rate_to_birr is required.", frappe.ValidationError)
	return {"fx_rate": record_fx_rate(currency, rate, rate_date or today())}


@frappe.whitelist()
def fetch_fx_rates_now():
	"""Manually pull live rates from the public source right now (Finance Manager/Admin), instead
	of waiting for the scheduled Global-mode fetch. Custom-mode sites simply never need this --
	setting rates by hand via set_fx_rate stays the default, fully-supported path. Returns the
	currencies actually recorded (empty if the source was unreachable; the existing cache stands)."""
	if not ({"Finance Manager", "Admin", "System Manager"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	recorded = fetch_daily_fx_rates()
	return {"recorded": recorded, "count": len(recorded)}


@frappe.whitelist()
def get_owed_commissions(contractor=None, destination_country=None, order="oldest", **kwargs):
	if not ({"Finance Manager", "Admin", "System Manager"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	contractor = contractor or kwargs.get("contractor_name")
	if not contractor:
		frappe.throw("contractor is required.", frappe.ValidationError)
	if not destination_country:
		destination_country = frappe.db.get_value("Contractor", contractor, "country")
	if not destination_country:
		return []
	return list_owed_commissions(contractor, destination_country, order)


@frappe.whitelist()
def create_commission_batch(contractor=None, destination_country=None, transaction_names=None, requested_advance_amount=None, **kwargs):
	"""Manual batching path (Part D: "both paths converge on one create_batch_request()
	function" — the other path is the automatic one inside finance_engine.accrue_commission).
	transaction_names selects which owed commissions to include (default: all owed for the
	contractor/country, which can include items carried over from prior batches via
	release_unpaid_items). requested_advance_amount records an up-front "pay this ASAP" ask."""
	if not ({"Finance Manager", "Admin", "System Manager"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	contractor = contractor or kwargs.get("contractor_name")
	if not contractor:
		frappe.throw("contractor is required.", frappe.ValidationError)
	if not destination_country:
		destination_country = frappe.db.get_value("Contractor", contractor, "country")
	if not destination_country:
		frappe.throw("destination_country is required.", frappe.ValidationError)
	if isinstance(transaction_names, str):
		transaction_names = frappe.parse_json(transaction_names)
	requested_advance_amount = requested_advance_amount if requested_advance_amount is not None else kwargs.get("requested_advance")
	batch = create_batch_request(contractor, destination_country, transaction_names, requested_advance_amount)
	return batch.as_dict()


@frappe.whitelist()
def write_off_batch(batch_name=None, write_off_amount=None, write_off_reason=None, **kwargs):
	"""Record an agreed discount on a batch (the agency pays less by negotiation). Books an Expense
	for the shortfall and, once advance + write-off cover the total, settles the batch. Amounts are
	in Birr, consistent with the rest of the batch."""
	if not ({"Finance Manager", "Admin"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	batch_name = batch_name or kwargs.get("batch") or kwargs.get("name")
	write_off_amount = write_off_amount if write_off_amount is not None else kwargs.get("amount")
	write_off_reason = write_off_reason or kwargs.get("reason")
	if not batch_name or not frappe.db.exists("Commission Batch Request", batch_name):
		frappe.throw("A valid batch_name is required.", frappe.ValidationError)
	return apply_batch_write_off(batch_name, write_off_amount, write_off_reason).as_dict()


@frappe.whitelist()
def release_unpaid_items(item_names=None, **kwargs):
	"""Carry unpaid items out of a (usually settled) batch back into the owed pool so they can be
	pulled into a new commission request. Each keeps a trace-back to its original batch."""
	if not ({"Finance Manager", "Admin"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	item_names = item_names if item_names is not None else kwargs.get("items")
	if isinstance(item_names, str):
		item_names = frappe.parse_json(item_names)
	return _release_unpaid_items(item_names)


@frappe.whitelist()
def list_commission_batches(contractor=None, status=None, destination_country=None, **kwargs):
	"""List commission batches (Finance view) with their money summary -- for picking a batch to
	settle / write off / inspect."""
	if not ({"Finance Manager", "Admin", "System Manager"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	filters = {}
	contractor = contractor or kwargs.get("contractor_name")
	if contractor:
		filters["contractor"] = contractor
	if status:
		filters["status"] = status
	if destination_country:
		filters["destination_country"] = destination_country
	return frappe.get_all(
		"Commission Batch Request",
		filters=filters,
		fields=[
			"name", "contractor", "destination_country", "status", "total_amount_birr",
			"requested_advance_amount", "advance_amount", "write_off_amount", "balance_due_birr",
			"settled_on", "creation",
		],
		order_by="creation desc",
	)


@frappe.whitelist()
def get_commission_batch(batch_name=None, **kwargs):
	"""Full batch detail incl. per-applicant item rows (name, amount, status, carried-from batch)
	-- the data behind the invoice PDF, for a batch/applicant listing screen."""
	if not ({"Finance Manager", "Admin", "System Manager"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	batch_name = batch_name or kwargs.get("batch") or kwargs.get("name")
	if not batch_name or not frappe.db.exists("Commission Batch Request", batch_name):
		frappe.throw("A valid batch_name is required.", frappe.ValidationError)
	batch = frappe.get_doc("Commission Batch Request", batch_name)
	items = []
	for row in batch.items:
		placement = frappe.db.get_value("Applicant Transaction", row.transaction, "placement")
		applicant = frappe.db.get_value("Placement", placement, "applicant") if placement else None
		items.append(
			{
				"item": row.name,
				"transaction": row.transaction,
				"placement": placement,
				"applicant": applicant,
				"full_name": frappe.db.get_value("Applicant", applicant, "full_name") if applicant else None,
				"amount_birr": frappe.db.get_value("Applicant Transaction", row.transaction, "amount_birr"),
				"status": row.status,
				"original_batch": row.get("original_batch"),
			}
		)
	detail = batch.as_dict()
	detail["items_detail"] = items
	return detail


@frappe.whitelist()
def settle_batch(batch_name, settlement_reference):
	if not ({"Finance Manager", "Admin"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	if not batch_name or not frappe.db.exists("Commission Batch Request", batch_name):
		frappe.throw("A valid batch_name is required.", frappe.ValidationError)
	batch = frappe.get_doc("Commission Batch Request", batch_name)
	# Dual-authorization / Segregation of duties:
	# An operational creator of the batch cannot be the sole approver/settler of large batches
	# unless they are the Administrator or hold the Admin role.
	if (
		batch.owner == frappe.session.user
		and frappe.session.user != "Administrator"
		and "Admin" not in frappe.get_roles()
		and flt(batch.total_amount_birr) > 100000
	):
		frappe.throw(
			"Four-eyes principle violation: The creator of a commission batch exceeding 100,000 ETB "
			"cannot be the sole settler. Another Finance Manager or Admin must settle this batch.",
			frappe.PermissionError,
		)
	return settle_batch_request(batch_name, settlement_reference).as_dict()


@frappe.whitelist()
def record_batch_advance(batch_name=None, advance_amount=None, advance_reference=None, **kwargs):
	"""Record a partial/advance payment received from the foreign agency against a commission
	batch, when they remit less than the full requested total. Sets advance_amount (+ reference
	and received-on date); the controller recomputes balance_due_birr and flips an open batch to
	Partially Settled. Full settlement still goes through settle_batch / settle_batch_items."""
	if not ({"Finance Manager", "Admin"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	batch_name = batch_name or kwargs.get("batch") or kwargs.get("name")
	advance_amount = advance_amount if advance_amount is not None else kwargs.get("amount")
	advance_reference = advance_reference or kwargs.get("reference")
	if not batch_name or not frappe.db.exists("Commission Batch Request", batch_name):
		frappe.throw("A valid batch_name is required.", frappe.ValidationError)
	if advance_amount is None:
		frappe.throw("advance_amount is required.", frappe.ValidationError)
	amount = flt(advance_amount)
	if amount <= 0:
		frappe.throw("advance_amount must be greater than zero.", frappe.ValidationError)

	batch = frappe.get_doc("Commission Batch Request", batch_name)
	# Reconcile against per-item payments + any write-off so total credited can't exceed the
	# obligation (audit N-1). All Birr -- foreign-currency remittances are converted before entry.
	accounted = flt(batch.paid_from_items()) + amount + flt(batch.write_off_amount)
	if accounted > flt(batch.total_amount_birr):
		frappe.throw(
			f"Paid-per-item ({batch.paid_from_items()}) + advance ({amount}) + write-off "
			f"({flt(batch.write_off_amount)}) cannot exceed the batch total "
			f"({batch.total_amount_birr or 0}). Use settle_batch for a full settlement.",
			frappe.ValidationError,
		)
	batch.advance_amount = amount
	if advance_reference:
		batch.advance_reference = advance_reference
	batch.advance_received_on = today()
	batch.save(ignore_permissions=True)
	log_action("Commission Batch Request", batch.name,
	           f"Advance received: {amount} Birr" + (f" (ref {advance_reference})" if advance_reference else ""))
	return batch.as_dict()


@frappe.whitelist()
def settle_batch_items(item_names):
	"""AGREED_SPEC.md Part 7.3 (backend-issues #09): explicit multi-select manual settlement,
	alongside upload_batch_payment_proof's best-effort parser -- marks specific Commission
	Batch Item child rows Paid and syncs each affected batch's status (Partially Settled until
	every item is Paid, then Settled)."""
	if not ({"Finance Manager", "Admin"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	if isinstance(item_names, str):
		item_names = frappe.parse_json(item_names)
	return mark_batch_items_paid(item_names)


@frappe.whitelist()
def upload_batch_payment_proof(batch_name, file_url):
	"""AGREED_SPEC.md Part 7.3 (backend-issues #09): parses a CSV or PDF listing paid applicant
	names (best-effort), fuzzy-matches against this batch's own item list, marks matched items
	Paid. Unmatched names stay Pending for manual settle_batch_items review -- never blocks."""
	if not ({"Finance Manager", "Admin"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	return match_batch_payment_proof(batch_name, file_url)


@frappe.whitelist()
def get_batch_invoice_pdf(batch_name):
	"""AGREED_SPEC.md Part 7.3 (backend-issues #09): on-demand PDF (applicant names + amounts),
	built fresh whenever requested, not pre-generated/stored at batch creation."""
	if not ({"Finance Manager", "Admin"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	frappe.local.response.filename = f"{batch_name}-invoice.pdf"
	frappe.local.response.filecontent = render_batch_invoice_pdf(batch_name)
	frappe.local.response.type = "pdf"
