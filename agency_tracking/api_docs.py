# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE

import json
import os
import frappe


@frappe.whitelist(allow_guest=True)
def get_swagger_spec():
	"""Returns the Swagger 2.0 / OpenAPI specification as a JSON object.
	Allowing guest access so external frontend apps and documentation viewers
	can inspect the schema without requiring an authenticated session first.
	"""
	# Search in app root and public asset folder
	app_path = frappe.get_app_path("agency_tracking")
	candidate_paths = [
		os.path.join(app_path, "public", "swagger.json"),
		os.path.join(os.path.dirname(app_path), "swagger.json"),
	]

	for path in candidate_paths:
		if os.path.exists(path):
			with open(path, "r", encoding="utf-8") as f:
				return json.load(f)

	frappe.throw("Swagger specification file not found.", frappe.DoesNotExistError)
