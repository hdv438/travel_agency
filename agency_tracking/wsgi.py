import os
import sys
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

def _resolve_default_site(base_sites_path):
	"""Find the active site directory to serve as fallback when the Host header
	does not match a specific site directory (e.g. Railway public URLs, proxies)."""
	# 1. currentsite.txt
	current_file = os.path.join(base_sites_path, "currentsite.txt")
	if os.path.exists(current_file):
		try:
			with open(current_file, "r") as f:
				s = f.read().strip()
				if s and os.path.exists(os.path.join(base_sites_path, s, "site_config.json")):
					return s
		except Exception:
			pass

	# 2. common_site_config.json default_site
	common_cfg = os.path.join(base_sites_path, "common_site_config.json")
	if os.path.exists(common_cfg):
		try:
			import json
			with open(common_cfg, "r") as f:
				cfg = json.load(f)
				s = cfg.get("default_site")
				if s and os.path.exists(os.path.join(base_sites_path, s, "site_config.json")):
					return s
		except Exception:
			pass

	# 3. First directory in sites/ containing site_config.json
	try:
		for item in sorted(os.listdir(base_sites_path)):
			if item != "assets" and os.path.exists(os.path.join(base_sites_path, item, "site_config.json")):
				return item
	except Exception:
		pass
	return None

_cached_default_site = None

class DynamicSiteMiddleware:
	"""Ensures requests from arbitrary domains (e.g. *.up.railway.app, load balancers, or proxies)
	always route to the active Frappe site instead of throwing 404 Site Not Found."""
	def __init__(self, app, base_sites_path):
		self.app = app
		self.base_sites_path = base_sites_path

	def __call__(self, environ, start_response):
		global _cached_default_site
		# If X-Frappe-Site-Name is not explicitly sent
		if "HTTP_X_FRAPPE_SITE_NAME" not in environ:
			host_header = environ.get("HTTP_HOST", "").split(":", 1)[0].strip()
			# Check if host exists as a site directory with site_config.json
			if not (host_header and os.path.exists(os.path.join(self.base_sites_path, host_header, "site_config.json"))):
				if not _cached_default_site or not os.path.exists(os.path.join(self.base_sites_path, _cached_default_site, "site_config.json")):
					_cached_default_site = _resolve_default_site(self.base_sites_path)
				if _cached_default_site:
					environ["HTTP_X_FRAPPE_SITE_NAME"] = _cached_default_site

		return self.app(environ, start_response)

# Base Frappe WSGI application
application = frappe.app.application

# Apply Dynamic Site Resolution Middleware
application = DynamicSiteMiddleware(application, sites_path)

# Wrap with Static/Asset middleware so standalone Gunicorn directly serves /assets and /files
if os.path.exists(assets_path):
	application = SharedDataMiddleware(application, {"/assets": assets_path})
else:
	application = SharedDataMiddleware(application, {"/assets": "assets"})

if os.path.exists(sites_path):
	application = StaticDataMiddleware(application, {"/files": os.path.abspath(sites_path)})
