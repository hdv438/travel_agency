# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# 2026-09-23: Applicant.validate now stores UPPERCASE_FIELDS in caps and rebuilds full_name from
# first/middle/last. Bring existing rows in line once, in SQL: no doc.save() (that would re-run
# the field floor / uniqueness checks on every historical row and bump `modified`).

import frappe


def execute():
	from agency_tracking.agency_tracking.doctype.applicant.applicant import UPPERCASE_FIELDS

	for fieldname in UPPERCASE_FIELDS:
		# Same as Applicant.normalize_uppercase_fields: uppercase, collapse runs of whitespace, trim.
		normalized = f"TRIM(REGEXP_REPLACE(UPPER(`{fieldname}`), '[[:space:]]+', ' '))"
		frappe.db.sql(
			f"""UPDATE `tabApplicant`
			SET `{fieldname}` = {normalized}
			WHERE `{fieldname}` IS NOT NULL AND `{fieldname}` <> '' AND BINARY `{fieldname}` <> BINARY {normalized}"""
		)
	frappe.db.sql(
		"""UPDATE `tabApplicant`
		SET full_name = CONCAT_WS(' ', NULLIF(first_name, ''), NULLIF(middle_name, ''), NULLIF(last_name, ''))
		WHERE CONCAT_WS(' ', NULLIF(first_name, ''), NULLIF(middle_name, ''), NULLIF(last_name, '')) <> ''
		AND BINARY COALESCE(full_name, '') <> BINARY CONCAT_WS(' ', NULLIF(first_name, ''), NULLIF(middle_name, ''), NULLIF(last_name, ''))"""
	)
	frappe.db.commit()
