# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE

import os
import re
import io
import datetime
import unicodedata

import frappe
from frappe.utils import getdate

try:
	from passporteye import read_mrz
except ImportError:
	read_mrz = None

try:
	import pycountry
except ImportError:
	pycountry = None

# ─────────────────────────────────────────────────────────────────────────────
# 1. ISO 3166-1 Alpha-3 Country Mapping & Constants
# ─────────────────────────────────────────────────────────────────────────────
ISO_ALPHA3_TO_COUNTRY = {
	"ETH": "Ethiopia",
	"SAU": "Saudi Arabia",
	"ARE": "United Arab Emirates",
	"KWT": "Kuwait",
	"QAT": "Qatar",
	"BHR": "Bahrain",
	"OMN": "Oman",
	"JOR": "Jordan",
	"LBN": "Lebanon",
	"KEN": "Kenya",
	"UGA": "Uganda",
	"SDN": "Sudan",
	"SSD": "South Sudan",
	"SOM": "Somalia",
	"DJI": "Djibouti",
	"EGY": "Egypt",
	"ERI": "Eritrea",
	"IND": "India",
	"PAK": "Pakistan",
	"BGD": "Bangladesh",
	"PHL": "Philippines",
	"IDN": "Indonesia",
	"NPL": "Nepal",
	"LKA": "Sri Lanka",
	"GBR": "United Kingdom",
	"USA": "United States",
	"CAN": "Canada",
	"AUS": "Australia",
	"DEU": "Germany",
	"FRA": "France",
	"ITA": "Italy",
	"ESP": "Spain",
	"TUR": "Turkey",
	"CHN": "China",
	"JPN": "Japan",
	"YEM": "Yemen",
	"IRQ": "Iraq",
	"SYR": "Syrian Arab Republic",
}

MONTH_MAP = {
	"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
	"JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12
}

MRZ_SEX_TO_GENDER = {"M": "Male", "F": "Female"}

# ─────────────────────────────────────────────────────────────────────────────
# 2. ICAO 9303 Checksum Decoder & Self-Correction Engine
# ─────────────────────────────────────────────────────────────────────────────
ICAO_WEIGHTS = [7, 3, 1]

CHAR_CONFUSIONS = {
	"O": ["0", "Q", "D", "U"],
	"0": ["O", "Q", "D", "U"],
	"I": ["1", "l", "|", "T", "J"],
	"1": ["I", "l", "|", "T", "J"],
	"S": ["5", "8", "$"],
	"5": ["S", "6"],
	"B": ["8", "6", "0", "E"],
	"8": ["B", "0", "3", "S"],
	"Z": ["2", "7"],
	"2": ["Z"],
	"G": ["6", "0", "C", "Q"],
	"6": ["G", "b", "5"],
	"D": ["0", "O", "Q"],
	"Q": ["0", "O", "G"],
	"U": ["V", "0"],
	"V": ["U", "<"],
	"K": ["<", "X"],
	"C": ["<", "G", "0"],
	"<": ["K", "C", "X", "(", " ", "_", "-"],
}


def icao_char_value(c):
	"""Returns integer value for ICAO 9303 checksum computation."""
	c = str(c).upper()
	if c.isdigit():
		return int(c)
	if 'A' <= c <= 'Z':
		return ord(c) - ord('A') + 10
	return 0


def compute_icao_checksum(text):
	"""Computes ICAO 9303 checksum digit for a given alphanumeric string."""
	total = 0
	for idx, char in enumerate(text):
		weight = ICAO_WEIGHTS[idx % 3]
		total += icao_char_value(char) * weight
	return total % 10


def verify_and_correct_checksum(data_str, expected_check_char, is_numeric=True):
	"""
	Validates data_str against expected_check_char.
	Uses OCR confusion map to find single character substitutions.
	"""
	data_clean = str(data_str).upper()
	check_char = str(expected_check_char).upper()

	if check_char in ("O", "D", "Q"):
		check_char = "0"
	elif check_char in ("I", "L", "|"):
		check_char = "1"
	elif check_char == "S":
		check_char = "5"
	elif check_char == "B":
		check_char = "8"
	elif check_char == "Z":
		check_char = "2"

	if not check_char.isdigit():
		return False, data_clean, check_char

	expected_check_val = int(check_char)
	computed = compute_icao_checksum(data_clean)

	if computed == expected_check_val and (not is_numeric or data_clean.isdigit()):
		return True, data_clean, str(expected_check_val)

	# Single-character substitution trial
	data_list = list(data_clean)
	positions = list(range(len(data_list)))
	if is_numeric:
		# Prioritize positions that currently contain non-digits
		positions.sort(key=lambda idx: 0 if not data_list[idx].isdigit() else 1)

	for pos in positions:
		ch = data_list[pos]
		confusions = CHAR_CONFUSIONS.get(ch, [])
		for alt in confusions:
			if is_numeric and not alt.isdigit():
				continue
			trial_list = list(data_list)
			trial_list[pos] = alt
			trial_str = "".join(trial_list)
			if is_numeric and not trial_str.isdigit():
				continue
			if compute_icao_checksum(trial_str) == expected_check_val:
				return True, trial_str, str(expected_check_val)

	return False, data_clean, check_char


# ─────────────────────────────────────────────────────────────────────────────
# 3. Clean and Parse MRZ Lines
# ─────────────────────────────────────────────────────────────────────────────
def clean_mrz_line(raw_line):
	"""Cleans noisy characters from an OCR'd MRZ line."""
	if not raw_line:
		return ""
	line = raw_line.strip().upper()
	line = line.replace("«", "<").replace("‹", "<").replace("(", "<").replace(")", "<")
	line = line.replace("{", "<").replace("}", "<").replace("[", "<").replace("]", "<")
	line = line.replace("_", "<").replace("-", "<").replace(" ", "")
	line = re.sub(r'[^A-Z0-9<]', '', line)
	return line


def parse_mrz_date(yymmdd_str, is_expiry=False):
	"""Converts YYMMDD string to YYYY-MM-DD."""
	if not yymmdd_str or len(yymmdd_str) < 6:
		return None
	try:
		yy = int(yymmdd_str[0:2])
		mm = int(yymmdd_str[2:4])
		dd = int(yymmdd_str[4:6])

		if mm < 1 or mm > 12 or dd < 1 or dd > 31:
			return None

		curr_year = datetime.datetime.now().year
		curr_yy = curr_year % 100

		if is_expiry:
			century = 2000 if yy <= curr_yy + 30 else 1900
		else:
			century = 1900 if yy > curr_yy else 2000

		full_year = century + yy
		return f"{full_year:04d}-{mm:02d}-{dd:02d}"
	except Exception:
		return None


def infer_passport_issue_date(passport_expiry_str):
	"""Infer passport issue date from expiry for a 5-year passport.

	Ethiopian (and ICAO-standard) passports are valid for 5 years, but the expiry printed is the
	*last valid day*, which is one day before the 5th anniversary of issue -- i.e.
	expiry = issue + 5 years - 1 day. So to recover the issue date we invert that exactly:
	issue = expiry - 5 years + 1 day. Example: expiry 2029-07-10 -> issue 2024-07-11 (matches the
	real passport, whereas a plain -5-years gave 2024-07-10, the "1-day variation" bug).

	This is still a derivation, not a read of the passport's printed issue date (the MRZ does not
	carry an issue date at all -- ICAO 9303 encodes only DOB and expiry). It is exact for the
	standard 5-years-minus-a-day passports; keep the field editable for manual correction.
	"""
	if not passport_expiry_str:
		return None
	try:
		from dateutil.relativedelta import relativedelta
		exp_date = getdate(passport_expiry_str)
		return str(exp_date - relativedelta(years=5) + relativedelta(days=1))
	except Exception:
		return None


def split_name_parts(surname, given_names):
	"""Split a passport name into (first, middle, last) using Ethiopian / ICAO ordering.

	Ethiopian names have no family surname: the sequence is own-name, father's name, grandfather's
	name -- and the passport puts the own name(s) in the "given names" field and the ancestral
	name(s) in the "surname" field. So the true ordered full name is given_names followed by
	surname. We rebuild that whole sequence and then take first = token[0], last = token[-1],
	middle = everything in between. This stops the middle (father's) name being mistaken for the
	last name when the surname field carries more than one token, and never drops the middle name.

	Returns (first, middle, last) with middle/last possibly None. Casing is left to the caller.
	"""
	given_tokens = [t for t in re.split(r"\s+", (given_names or "").replace("<", " ").strip()) if t]
	surname_tokens = [t for t in re.split(r"\s+", (surname or "").replace("<", " ").strip()) if t]
	seq = given_tokens + surname_tokens
	if not seq:
		return "", None, None
	first = seq[0]
	last = seq[-1] if len(seq) >= 2 else None
	middle = " ".join(seq[1:-1]) if len(seq) > 2 else None
	return first, middle, last


def parse_mrz_td3(line1, line2):
	"""
	Parses standard Type 3 (TD3) Passport MRZ (2 lines x 44 characters).
	Example:
	Line 1: PQETHWACHAMO<<ASNEKECH<TEDESSE<<<<<<<<<<<<<<<<
	Line 2: EQ25760963ETH0012027F30051210<<<<<<<<<<<<<<04
	"""
	result = {
		"format": "TD3",
		"doc_type": "Passport",
		"raw_line1": line1,
		"raw_line2": line2,
		"is_valid": True,
		"checksum_validation": {},
	}

	line1 = (line1 + "<" * 44)[:44]
	line2 = (line2 + "<" * 44)[:44]

	# --- Line 1 Breakdown ---
	doc_code = line1[0:2].replace("<", "")
	issuing_country_code = line1[2:5].replace("<", "")
	name_field = line1[5:44]

	name_parts = name_field.split("<<")
	surname = name_parts[0].replace("<", " ").strip()
	given_names = ""
	if len(name_parts) > 1:
		given_names = name_parts[1].replace("<", " ").strip()

	# Ordered split across BOTH fields (given names + surname) so the middle name is never lost
	# nor merged into the last name -- see split_name_parts.
	first_name, middle_name, last_name = split_name_parts(surname, given_names)

	# --- Line 2 Breakdown ---
	raw_doc_num = line2[0:9]
	raw_doc_check = line2[9]
	nationality_code = line2[10:13].replace("<", "")
	raw_dob = line2[13:19]
	raw_dob_check = line2[19]
	sex_char = line2[20].upper()
	raw_expiry = line2[21:27]
	raw_expiry_check = line2[27]
	raw_optional = line2[28:42]

	val_doc, corr_doc_num, corr_doc_check = verify_and_correct_checksum(raw_doc_num, raw_doc_check, is_numeric=False)
	clean_passport_num = corr_doc_num.replace("<", "").strip()
	result["checksum_validation"]["passport_number"] = {
		"valid": val_doc, "raw": raw_doc_num, "clean": clean_passport_num, "check": corr_doc_check
	}

	val_dob, corr_dob, corr_dob_check = verify_and_correct_checksum(raw_dob, raw_dob_check, is_numeric=True)
	result["checksum_validation"]["date_of_birth"] = {
		"valid": val_dob, "raw": raw_dob, "corrected": corr_dob, "check": corr_dob_check
	}

	val_exp, corr_exp, corr_exp_check = verify_and_correct_checksum(raw_expiry, raw_expiry_check, is_numeric=True)
	result["checksum_validation"]["expiry_date"] = {
		"valid": val_exp, "raw": raw_expiry, "corrected": corr_exp, "check": corr_exp_check
	}

	# No silent placeholders (audit G-002): emit None for anything the scan didn't actually yield --
	# never "Applicant"/"Ethiopia"/"Female". map_mrz_fields skips None, so blanks stay blank for a
	# human to fill rather than being seeded with fabricated data.
	result["passport_number"] = clean_passport_num or None
	result["first_name"] = first_name.title() if first_name else None
	result["middle_name"] = middle_name.title() if middle_name else None
	result["last_name"] = last_name.title() if last_name else None

	parts = [result["first_name"], result["middle_name"], result["last_name"]]
	result["full_name"] = " ".join([p for p in parts if p]).strip() or None

	result["nationality"] = _resolve_country_name(nationality_code) or ISO_ALPHA3_TO_COUNTRY.get(nationality_code)
	result["place_of_issue"] = _resolve_country_name(issuing_country_code) or ISO_ALPHA3_TO_COUNTRY.get(issuing_country_code)

	result["date_of_birth"] = parse_mrz_date(corr_dob, is_expiry=False)
	result["passport_expiry"] = parse_mrz_date(corr_exp, is_expiry=True)
	result["passport_expiry_date"] = result["passport_expiry"]
	result["passport_issue_date"] = infer_passport_issue_date(result["passport_expiry"])

	result["gender"] = MRZ_SEX_TO_GENDER.get(sex_char)

	clean_opt = raw_optional.replace("<", "").strip()
	if clean_opt:
		result["national_id"] = clean_opt

	return result


def parse_mrz_td1(line1, line2, line3):
	"""Parses Type 1 (TD1) ID / Travel Card MRZ (3 lines x 30 characters)."""
	line1 = (line1 + "<" * 30)[:30]
	line2 = (line2 + "<" * 30)[:30]
	line3 = (line3 + "<" * 30)[:30]

	issuing_country_code = line1[2:5].replace("<", "")
	raw_doc_num = line1[5:14]
	raw_doc_check = line1[14]

	raw_dob = line2[0:6]
	raw_dob_check = line2[6]
	sex_char = line2[7].upper()
	raw_expiry = line2[8:14]
	raw_expiry_check = line2[14]
	nationality_code = line2[15:18].replace("<", "")

	name_parts = line3.split("<<")
	surname = name_parts[0].replace("<", " ").strip()
	given_names = name_parts[1].replace("<", " ").strip() if len(name_parts) > 1 else ""
	first_name, middle_name, last_name = split_name_parts(surname, given_names)

	val_doc, corr_doc_num, _ = verify_and_correct_checksum(raw_doc_num, raw_doc_check, is_numeric=False)
	val_dob, corr_dob, _ = verify_and_correct_checksum(raw_dob, raw_dob_check)
	val_exp, corr_exp, _ = verify_and_correct_checksum(raw_expiry, raw_expiry_check)

	exp_date = parse_mrz_date(corr_exp, is_expiry=True)

	# No silent placeholders (audit G-002) -- None for anything not actually read.
	return {
		"format": "TD1",
		"doc_type": "Identity Card",
		"checksum_validation": {
			"passport_number": {"valid": val_doc},
			"date_of_birth": {"valid": val_dob},
			"expiry_date": {"valid": val_exp},
		},
		"passport_number": corr_doc_num.replace("<", "").strip() or None,
		"first_name": first_name.title() if first_name else None,
		"middle_name": middle_name.title() if middle_name else None,
		"last_name": last_name.title() if last_name else None,
		"full_name": " ".join(filter(None, [first_name, middle_name, last_name])).title() or None,
		"nationality": _resolve_country_name(nationality_code) or ISO_ALPHA3_TO_COUNTRY.get(nationality_code),
		"place_of_issue": _resolve_country_name(issuing_country_code) or ISO_ALPHA3_TO_COUNTRY.get(issuing_country_code),
		"date_of_birth": parse_mrz_date(corr_dob, is_expiry=False),
		"passport_expiry": exp_date,
		"passport_expiry_date": exp_date,
		"passport_issue_date": infer_passport_issue_date(exp_date),
		"gender": MRZ_SEX_TO_GENDER.get(sex_char),
	}


def extract_mrz_from_raw_text(raw_text):
	"""Searches OCR text streams for MRZ lines or fallback visual passport data."""
	if not raw_text:
		return None

	raw_lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
	lines = [clean_mrz_line(l) for l in raw_lines]
	lines = [l for l in lines if len(l) >= 20]

	# Printed issue date off the same text we already have (MRZ has none) — overrides the derived
	# one on whichever MRZ result we return below.
	printed_issue = find_printed_issue_date(raw_text)

	# 1. Look for TD3 lines (starts with P, PQ, PA, PB, etc. or contains <<)
	for i in range(len(lines)):
		l1 = lines[i]
		is_l1_mrz = (
			(l1.startswith("P") and len(l1) >= 28) or
			("<<" in l1 and len(l1) >= 28) or
			("ETH" in l1[:8] and len(l1) >= 28)
		)
		if is_l1_mrz and (i + 1 < len(lines)):
			l2 = lines[i + 1]
			if len(l2) >= 28:
				return _apply_printed_issue(parse_mrz_td3(l1, l2), printed_issue)

	# 2. Look for any adjacent lines with << or passport numbers
	for i in range(len(lines) - 1):
		l1 = lines[i]
		l2 = lines[i + 1]
		if (len(l1) >= 30 and len(l2) >= 30) and ("<" in l1 or "<" in l2):
			return _apply_printed_issue(parse_mrz_td3(l1, l2), printed_issue)

	# 3. Look for TD1 (3 lines)
	for i in range(len(lines) - 2):
		l1, l2, l3 = lines[i], lines[i + 1], lines[i + 2]
		if 25 <= len(l1) <= 35 and 25 <= len(l2) <= 35 and 25 <= len(l3) <= 35:
			return _apply_printed_issue(parse_mrz_td1(l1, l2, l3), printed_issue)

	return extract_visual_passport_data(raw_text)


def _parse_visual_date(date_str):
	"""Parses visual passport dates like '02 DEC 00' or '13 MAY 25' or '12 MAY 2030'."""
	if not date_str:
		return None
	m = re.search(r'([0-9]{1,2})\s*([A-Za-z]{3})\s*([0-9]{2,4})', date_str)
	if m:
		dd = int(m.group(1))
		mon_str = m.group(2).upper()
		yy_str = m.group(3)
		mm = MONTH_MAP.get(mon_str, 1)
		if len(yy_str) == 2:
			yy = int(yy_str)
			curr_yy = datetime.datetime.now().year % 100
			century = 2000 if yy <= curr_yy + 30 else 1900
			full_year = century + yy
		else:
			full_year = int(yy_str)
		return f"{full_year:04d}-{mm:02d}-{dd:02d}"
	return normalize_date_string(date_str)


def normalize_date_string(date_str):
	"""Converts various date formats (DD/MM/YYYY, YYYY-MM-DD, etc.) to ISO YYYY-MM-DD."""
	if not date_str:
		return None
	d = str(date_str).strip()
	m = re.search(r'([0-9]{1,4}[-/.][0-9]{1,2}[-/.][0-9]{1,4})', d)
	if not m:
		return None
	raw = m.group(1).replace("/", "-").replace(".", "-")
	parts = raw.split("-")
	try:
		if len(parts) == 3:
			if len(parts[0]) == 4:
				year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
			else:
				day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
			return str(datetime.date(year, month, day))
	except Exception:
		pass
	try:
		return str(getdate(d))
	except Exception:
		return None


def find_printed_issue_date(raw_text):
	"""Read the printed 'Date of Issue' from the passport's visual zone, off text we ALREADY
	extracted (PDF text stream or the OCR the MRZ step already ran) -- no extra OCR pass. The MRZ
	itself carries no issue date (ICAO 9303), so when the passport page prints one this is the
	accurate source; callers fall back to the expiry-based derivation only when it's absent.
	Returns ISO YYYY-MM-DD or None."""
	if not raw_text:
		return None
	date_token = r"([0-9]{1,2}\s*[A-Za-z]{3}\s*[0-9]{2,4}|[0-9]{1,4}[-/.][0-9]{1,2}[-/.][0-9]{1,4})"
	# "Date of issue"/"Issue date" — but never "Date of expiry", which is matched by excluding a
	# following "exp"/"expiry" between the label and the date.
	pattern = re.compile(r"(?:Date\s*of\s*Issue|Issue\s*Date)\s*[:=]?\s*" + date_token, re.I)
	for line in raw_text.splitlines():
		if re.search(r"expir", line, re.I) and not re.search(r"issue", line, re.I):
			continue
		m = pattern.search(line)
		if m:
			iso = _parse_visual_date(m.group(1))
			if iso:
				return iso
	return None


def _apply_printed_issue(result, printed_issue):
	"""Override a parser result's derived issue date with a printed one when we found it."""
	if result and printed_issue:
		result["passport_issue_date"] = printed_issue
	return result


def extract_visual_passport_data(raw_text):
	"""Fallback visual label-based passport field extractor."""
	if not raw_text:
		return None

	lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
	printed_issue = find_printed_issue_date(raw_text)
	# Visual (non-MRZ) extraction is the low-confidence last resort -- no fabricated defaults
	# (audit G-002) and the whole result is flagged needs_review in map_mrz_fields.
	data = {
		"format": "Visual",
		"doc_type": "Passport",
		"passport_number": None,
		"first_name": None,
		"middle_name": None,
		"last_name": None,
		"full_name": None,
		"nationality": None,
		"place_of_issue": None,
		"date_of_birth": None,
		"passport_issue_date": None,
		"passport_expiry": None,
		"passport_expiry_date": None,
		"gender": None,
	}

	for i, line in enumerate(lines):
		# Passport number: e.g. Passport No: EQ2576096 or EP1234567
		if re.search(r'(?:Passport\s*No|Passport\s*Number|Doc\s*No)', line, re.I):
			m = re.search(r'\b([A-Z]{1,2}[0-9]{6,9})\b', line)
			if m:
				data["passport_number"] = m.group(1)
			elif i + 1 < len(lines):
				m2 = re.search(r'\b([A-Z]{1,2}[0-9]{6,9})\b', lines[i + 1])
				if m2:
					data["passport_number"] = m2.group(1)

		# Given Names
		if re.search(r'(?:Given\s*Names?|First\s*Name)', line, re.I):
			val = re.sub(r'^(?:Given\s*Names?|First\s*Name)[:=\s]+', '', line, flags=re.I).strip()
			if val and not re.search(r'Passport|Country|Sex|Date', val, re.I):
				parts = val.split()
				if parts:
					data["first_name"] = parts[0].title()
					if len(parts) > 1:
						data["middle_name"] = " ".join(parts[1:]).title()

		# Surname
		if re.search(r'(?:Surname|Last\s*Name)', line, re.I):
			val = re.sub(r'^(?:Surname|Last\s*Name)[:=\s]+', '', line, flags=re.I).strip()
			if val and not re.search(r'Passport|Country|Sex|Date', val, re.I):
				data["last_name"] = val.title()

		# Date of birth
		if re.search(r'(?:Date\s*of\s*birth|DOB|Birth\s*Date)', line, re.I):
			val = re.sub(r'^(?:Date\s*of\s*birth|DOB|Birth\s*Date)[:=\s]+', '', line, flags=re.I).strip()
			parsed_d = _parse_visual_date(val)
			if parsed_d:
				data["date_of_birth"] = parsed_d

		# Expiry date
		if re.search(r'(?:Date\s*of\s*expiry|Expiry\s*Date|Expiration)', line, re.I):
			val = re.sub(r'^(?:Date\s*of\s*expiry|Expiry\s*Date|Expiration)[:=\s]+', '', line, flags=re.I).strip()
			parsed_e = _parse_visual_date(val)
			if parsed_e:
				data["passport_expiry"] = parsed_e
				data["passport_expiry_date"] = parsed_e
				# Printed issue date wins; derive only when the page didn't print one.
				data["passport_issue_date"] = printed_issue or infer_passport_issue_date(parsed_e)

		# Sex / Gender
		if re.search(r'\b(?:Sex|Gender)\b', line, re.I):
			if re.search(r'\b(?:M|Male)\b', line, re.I):
				data["gender"] = "Male"
			elif re.search(r'\b(?:F|Female)\b', line, re.I):
				data["gender"] = "Female"

	# Printed issue date even when no expiry line was found on the page.
	if printed_issue and not data.get("passport_issue_date"):
		data["passport_issue_date"] = printed_issue

	# Re-split across given + surname so a multi-token surname doesn't swallow the middle name.
	if data.get("first_name") or data.get("last_name"):
		given = " ".join(filter(None, [data.get("first_name"), data.get("middle_name")]))
		first, middle, last = split_name_parts(data.get("last_name"), given)
		data["first_name"] = first.title() if first else data.get("first_name")
		data["middle_name"] = middle.title() if middle else None
		data["last_name"] = last.title() if last else None

	if data.get("passport_number") or (data.get("first_name") and data.get("date_of_birth")):
		return data
	return None


# ─────────────────────────────────────────────────────────────────────────────
# 4. Helper Resolution & Pure Mapping
# ─────────────────────────────────────────────────────────────────────────────
def _resolve_country_name(alpha_3: str) -> str | None:
	"""ISO alpha-3 (MRZ) -> Frappe's own Country doctype name."""
	if not alpha_3:
		return None
	clean = alpha_3.strip().upper()
	if clean in ISO_ALPHA3_TO_COUNTRY:
		candidate = ISO_ALPHA3_TO_COUNTRY[clean]
		try:
			if getattr(frappe, "db", None) and frappe.db and frappe.db.exists("Country", candidate):
				return candidate
		except Exception:
			pass
		return candidate

	if pycountry:
		try:
			country = pycountry.countries.get(alpha_3=clean)
			if country:
				try:
					if getattr(frappe, "db", None) and frappe.db:
						name = frappe.db.get_value("Country", {"code": country.alpha_2.lower()}, "name")
						if name:
							return name
				except Exception:
					pass
				return country.name
		except Exception:
			pass

	try:
		if getattr(frappe, "db", None) and frappe.db:
			return frappe.db.get_value("Country", {"name": ["like", f"{clean}%"]}, "name")
	except Exception:
		pass

	return None


def _mrz_date_to_iso(mrz_date: str) -> str | None:
	"""MRZ dates are YYMMDD."""
	return parse_mrz_date(mrz_date, is_expiry=False)


def _normalize_mrz_date(value, is_expiry=False) -> str | None:
	"""Coerce any date shape a parser might hand us into ISO YYYY-MM-DD.

	Handles: already-ISO strings (pass through), raw 6-digit MRZ YYMMDD (PassportEye), and the
	usual DD/MM/YYYY-style visual dates. is_expiry drives the century window for 2-digit years
	(expiry rolls forward, birth rolls back)."""
	if not value:
		return None
	s = str(value).strip()
	if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
		return s
	if re.fullmatch(r"\d{6}", s):
		return parse_mrz_date(s, is_expiry=is_expiry)
	return normalize_date_string(s)


def map_mrz_fields(mrz_dict: dict) -> dict:
	"""Pure mapping from MRZ dictionary to Applicant fieldnames.

	Audit G-001/G-002: a field whose ICAO checksum could NOT be validated/self-corrected is dropped
	(not auto-filled) and the whole result is flagged `needs_passport_review` so staff verify it by
	hand -- rather than writing an unverified passport number/DOB/expiry as if it were confirmed.
	Visual (non-MRZ) extractions are always flagged for review. Fields the scan didn't yield are
	simply absent (no fabricated Ethiopia/Female/"Applicant" defaults)."""
	fields = {}
	cv = mrz_dict.get("checksum_validation") or {}

	def _ok(key):
		entry = cv.get(key)
		# Unknown (e.g. a raw PassportEye dict with no checksum info) -> don't drop; only a proven
		# False suppresses the field.
		return entry.get("valid", True) if isinstance(entry, dict) else True

	needs_review = mrz_dict.get("format") == "Visual"

	doc_num = (mrz_dict.get("number") or mrz_dict.get("passport_number") or "").strip()
	if doc_num and _ok("passport_number"):
		fields["passport_number"] = doc_num
	elif doc_num:
		needs_review = True

	# Expiry: our own parsers already give ISO; PassportEye gives raw YYMMDD under "expiration_date"
	# (must use is_expiry=True so 29 -> 2029, not 1929).
	exp_date = (
		mrz_dict.get("passport_expiry_date")
		or mrz_dict.get("passport_expiry")
		or _normalize_mrz_date(mrz_dict.get("expiration_date"), is_expiry=True)
	)
	if exp_date and _ok("expiry_date"):
		fields["passport_expiry_date"] = exp_date
		# Prefer a printed/carried-through issue date; derive from expiry only when none was found.
		issue_date = _normalize_mrz_date(mrz_dict.get("passport_issue_date")) or infer_passport_issue_date(exp_date)
		if issue_date:
			fields["passport_issue_date"] = issue_date
	elif exp_date:
		needs_review = True

	# DOB: always normalise to ISO before returning it, so the endpoint JSON never carries a raw
	# YYMMDD (which the frontend can't use and which reads as "no DOB").
	dob = _normalize_mrz_date(mrz_dict.get("date_of_birth"), is_expiry=False)
	if dob and _ok("date_of_birth"):
		fields["date_of_birth"] = dob
	elif dob:
		needs_review = True

	sex = (mrz_dict.get("gender") or mrz_dict.get("sex") or "").strip().upper()
	if sex in ("M", "MALE"):
		fields["gender"] = "Male"
	elif sex in ("F", "FEMALE"):
		fields["gender"] = "Female"

	# Names: prefer a first/middle/last already split by our own parsers; otherwise (e.g. a raw
	# PassportEye dict with surname/names) split here. Always carry the middle name through.
	first = mrz_dict.get("first_name")
	middle = mrz_dict.get("middle_name")
	last = mrz_dict.get("last_name")
	if not (first or last):
		first, middle, last = split_name_parts(mrz_dict.get("surname"), mrz_dict.get("names"))
	if first:
		fields["first_name"] = str(first).title()
	if middle:
		fields["middle_name"] = str(middle).title()
	if last:
		fields["last_name"] = str(last).title()

	nat = mrz_dict.get("nationality")
	if not nat:
		nat_alpha3 = (mrz_dict.get("nationality_code") or mrz_dict.get("country") or "").strip().upper()
		nat = _resolve_country_name(nat_alpha3) or ISO_ALPHA3_TO_COUNTRY.get(nat_alpha3)
	if nat:
		fields["nationality"] = nat

	issue_place = mrz_dict.get("place_of_issue")
	if issue_place:
		fields["passport_issue_place"] = issue_place

	if needs_review:
		fields["needs_passport_review"] = 1

	return fields


# ─────────────────────────────────────────────────────────────────────────────
# 5. Master Passport MRZ File Parser
# ─────────────────────────────────────────────────────────────────────────────
def parse_passport_mrz(file_path: str) -> dict:
	"""
	Given a filesystem path to a passport scan/photo/PDF, extracts MRZ and returns
	Applicant field updates. Uses multiple parsing strategies:
	1. Text stream extraction (PyMuPDF / pypdf) with ICAO 9303 checksum self-correction
	2. PassportEye MRZ image OCR
	3. Visual regex fallback
	Never raises exceptions — gracefully logs and returns empty dict on failure.
	"""
	if not file_path or not os.path.exists(file_path):
		return {}

	# 1. If PDF document, extract text stream directly
	if file_path.lower().endswith(".pdf"):
		try:
			from agency_tracking.contract_parser import extract_text_from_pdf
			raw_text = extract_text_from_pdf(file_path)
			if raw_text:
				parsed = extract_mrz_from_raw_text(raw_text)
				if parsed:
					return map_mrz_fields(parsed)
		except Exception:
			pass

	# 2. Use PassportEye if available
	if read_mrz:
		try:
			mrz = read_mrz(file_path)
			if mrz:
				mrz_dict = mrz.to_dict()
				# If raw lines exist, run through ICAO 9303 checksum validator
				if mrz_dict.get("raw_text"):
					parsed_raw = extract_mrz_from_raw_text(mrz_dict["raw_text"])
					if parsed_raw:
						return map_mrz_fields(parsed_raw)
				return map_mrz_fields(mrz_dict)
		except Exception:
			pass

	# 3. Read image as raw text if pytesseract available
	try:
		import pytesseract
		from PIL import Image
		img = Image.open(file_path)
		ocr_text = pytesseract.image_to_string(img)
		if ocr_text:
			parsed = extract_mrz_from_raw_text(ocr_text)
			if parsed:
				return map_mrz_fields(parsed)
	except Exception:
		pass

	return {}


@frappe.whitelist()
def parse_passport_file(file_url: str) -> dict:
	"""Whitelisted endpoint to parse an uploaded passport scan. Internal staff only (audit G-004:
	was ungated) and it resolves ONLY a real uploaded File record -- it never treats the argument
	as a raw filesystem path, closing the arbitrary-local-file-read hole."""
	from agency_tracking.roles import INTERNAL_STAFF_ROLES

	if frappe.session.user != "Administrator" and not (INTERNAL_STAFF_ROLES & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	file_doc = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not file_doc:
		frappe.throw("A valid uploaded File is required.", frappe.ValidationError)
	file_path = frappe.get_doc("File", file_doc).get_full_path()
	return parse_passport_mrz(file_path)


