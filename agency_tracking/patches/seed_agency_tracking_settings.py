# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# 2026-09-07: Agency Tracking Settings (our own agency's letterhead/bank block on generated
# Commission Invoice PDFs) ships with the Data/Small Text field defaults already set to Anwar
# Sultan's real details -- see agency_tracking_settings.json -- but "Attach Image" fields (logo,
# stamp_image) can't carry a static default value, they need an actual File doc. This patch
# attaches the same two images bundled from the original Anwar Sultan template
# (templates/agency_assets/) so a fresh install's invoice PDF looks identical to that template,
# not just in text. Only fills fields that are still empty -- never overwrites a value someone
# already configured.
#
# Best-effort (2026-09-07 fix): a missing/unreadable bundled asset (e.g. a deploy environment
# whose build didn't carry the file for some packaging-specific reason) must never fail the
# whole `bench migrate` -- these are cosmetic branding defaults, not something a site needs to
# come up, and an Admin can always upload them by hand via Agency Tracking Settings afterward.
# Log and move on instead of letting frappe.log_error's own DB write (site not fully migrated
# yet at this point) become a second failure point either.

import frappe


def execute():
	settings = frappe.get_single("Agency Tracking Settings")
	changed = False

	if not settings.logo:
		logo = _attach_bundled_image("anwar_sultan_logo.png", "logo")
		if logo:
			settings.logo = logo
			changed = True

	if not settings.stamp_image:
		stamp = _attach_bundled_image("anwar_sultan_stamp.png", "stamp_image")
		if stamp:
			settings.stamp_image = stamp
			changed = True

	if changed:
		settings.save(ignore_permissions=True)
		frappe.db.commit()


def _attach_bundled_image(filename, fieldname):
	path = frappe.get_app_path("agency_tracking", "templates", "agency_assets", filename)
	try:
		with open(path, "rb") as f:
			content = f.read()
	except OSError as e:
		print(f"seed_agency_tracking_settings: skipping {filename} ({fieldname}), unreadable at {path}: {e}")
		return None
	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": filename,
			"attached_to_doctype": "Agency Tracking Settings",
			"attached_to_name": "Agency Tracking Settings",
			"attached_to_field": fieldname,
			"content": content,
			"is_private": 0,
		}
	)
	file_doc.insert(ignore_permissions=True)
	return file_doc.file_url
