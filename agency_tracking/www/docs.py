# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE

import frappe

no_cache = 1


def get_context(context):
	context.no_header = 1
	context.no_sidebar = 1
	context.show_sidebar = False
	context.title = "Agency Tracking API Documentation"
