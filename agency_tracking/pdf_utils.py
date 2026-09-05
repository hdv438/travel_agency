# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Shared PDF-rendering helpers for the app's generated documents (CV, Injaz). Kept in one place
# so every generated document resolves file attachments and renders the same way.

import base64
import io
import os

import frappe

# Code128 module patterns (values 0-106). Each string is six digits: alternating bar/space widths
# in modules, starting with a bar. 103=Start B, 106=Stop (with its trailing bar).
_CODE128_PATTERNS = [
	"212222", "222122", "222221", "121223", "121322", "131222", "122213", "122312", "132212", "221213",
	"221312", "231212", "112232", "122132", "122231", "113222", "123122", "123221", "223211", "221132",
	"221231", "213212", "223112", "312131", "311222", "321122", "321221", "312212", "322112", "322211",
	"212123", "212321", "232121", "111323", "131123", "131321", "112313", "132113", "132311", "211313",
	"231113", "231311", "112133", "112331", "132131", "113123", "113321", "133121", "313121", "211331",
	"231131", "213113", "213311", "213131", "311123", "311321", "331121", "312113", "312311", "332111",
	"314111", "221411", "431111", "111224", "111422", "121124", "121421", "141122", "141221", "112214",
	"112412", "122114", "122411", "142112", "142211", "241211", "221114", "413111", "241112", "134111",
	"111242", "121142", "121241", "114212", "124112", "124211", "411212", "421112", "421211", "212141",
	"214121", "412121", "111143", "111341", "131141", "114113", "114311", "411113", "411311", "113141",
	"114131", "311141", "411131", "211412", "211214", "211232", "2331112",
]


def code128_b_datauri(data, module_px=2, height_px=48, quiet=10):
	"""Render an ASCII string as a Code128-B barcode PNG and return it as a data: URI.

	Pure-Pillow so it works offline with no barcode package. Returns None for empty input (the
	template then simply shows no barcode)."""
	if not data:
		return None
	from PIL import Image, ImageDraw

	values = [104]  # Start Code B
	for ch in str(data):
		code = ord(ch)
		if 32 <= code <= 126:
			values.append(code - 32)
	checksum = (values[0] + sum(v * i for i, v in enumerate(values[1:], start=1))) % 103
	values.append(checksum)
	values.append(106)  # Stop

	widths = []
	for v in values:
		for w in _CODE128_PATTERNS[v]:
			widths.append(int(w))

	total_modules = sum(widths)
	width_px = total_modules * module_px + quiet * 2 * module_px
	img = Image.new("RGB", (width_px, height_px), "white")
	draw = ImageDraw.Draw(img)
	x = quiet * module_px
	bar = True  # patterns start with a bar
	for w in widths:
		w_px = w * module_px
		if bar:
			draw.rectangle([x, 0, x + w_px - 1, height_px - 1], fill="black")
		x += w_px
		bar = not bar

	buf = io.BytesIO()
	img.save(buf, format="PNG")
	return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def asset_datauri(*path_parts):
	"""Base64 data: URI for a static image bundled in the app (e.g. the MoFA emblem). Robust for
	wkhtmltopdf, which cannot fetch app-relative URLs. Returns None if the file is missing."""
	path = frappe.get_app_path("agency_tracking", *path_parts)
	if not os.path.exists(path):
		return None
	ext = os.path.splitext(path)[1].lstrip(".").lower() or "png"
	with open(path, "rb") as f:
		return f"data:image/{ext};base64," + base64.b64encode(f.read()).decode()


def resolve_file_src(url):
	"""Turn a stored Frappe file URL into something wkhtmltopdf can actually load.

	Private files (/private/files/...) are not readable over HTTP without an authenticated
	session, and even public /files URLs are unreliable inside the headless PDF renderer. When
	the file exists on disk we hand wkhtmltopdf an absolute file:// path so the image embeds
	directly; otherwise we pass the original value through unchanged (external URLs, data URIs,
	or a not-yet-present file — the template just shows its empty-state placeholder)."""
	if not url:
		return None
	if url.startswith(("http://", "https://", "data:", "file://")):
		return url

	base = rel = None
	if url.startswith("/private/files/"):
		base, rel = "private", url[len("/private/files/") :]
	elif url.startswith("/files/"):
		base, rel = "public", url[len("/files/") :]

	if base:
		path = frappe.get_site_path(base, "files", rel)
		if os.path.exists(path):
			return "file://" + os.path.abspath(path)
	return url


def render_pdf(template, context):
	"""Render a Jinja template path to PDF bytes via Frappe's standard wkhtmltopdf path."""
	html = frappe.render_template(template, context)
	return frappe.utils.pdf.get_pdf(html)
