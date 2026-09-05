import os
import frappe.app
from werkzeug.middleware.shared_data import SharedDataMiddleware
from frappe.middlewares import StaticDataMiddleware

sites_path = os.environ.get("SITES_PATH")
if not sites_path or not os.path.exists(sites_path):
	candidates = [
		os.path.abspath("sites"),
		os.path.abspath("."),
		os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "sites")),
		"/home/frappe/bench/sites",
	]
	for c in candidates:
		if os.path.exists(os.path.join(c, "assets")):
			sites_path = c
			break
	if not sites_path:
		sites_path = os.path.abspath("sites") if os.path.exists("sites") else os.path.abspath(".")

assets_path = os.path.join(sites_path, "assets")

# Base Frappe WSGI application
application = frappe.app.application

# Wrap with Static/Asset middleware so standalone Gunicorn directly serves /assets and /files
if os.path.exists(assets_path):
	application = SharedDataMiddleware(application, {"/assets": assets_path})
else:
	application = SharedDataMiddleware(application, {"/assets": "assets"})

if os.path.exists(sites_path):
	application = StaticDataMiddleware(application, {"/files": os.path.abspath(sites_path)})

