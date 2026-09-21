# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE

import frappe


def execute():
	"""Raises System Settings' Max File Size from Frappe's 25MB default to 500MB (2026-09-21).

	The 25MB default made sense when uploads stayed on local disk forever -- it doesn't anymore:
	receipts/photos/videos now migrate to R2 shortly after upload (storage_engine.migrate_attach_to_r2),
	so local disk is only a brief staging area, not permanent storage. A phone-shot candidate
	intro video (Applicant.experience_video) routinely exceeds 25MB and was hitting this cap
	outright before it ever reached R2.

	500MB, not unbounded: the upload/migration path fully buffers the file in process memory
	(File.get_content() then a single R2 put_object call, no streaming/multipart), so an
	unbounded cap risks a worker OOM on a single huge upload. 500MB comfortably covers a real
	short candidate video while still bounding worst-case memory use per upload.
	"""
	try:
		settings = frappe.get_doc("System Settings")
		settings.max_file_size = 500
		settings.flags.ignore_mandatory = True
		settings.save(ignore_permissions=True)
	except Exception:
		frappe.db.set_single_value("System Settings", "max_file_size", 500)
	frappe.db.commit()
