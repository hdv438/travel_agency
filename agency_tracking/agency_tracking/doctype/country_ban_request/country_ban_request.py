# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# 2026-09-23: a staff member blocked by an active Applicant Country Ban asks a Manager/Admin to
# either Override it for one specific action (a one-time pass -- status Approved until the
# blocked action is retried and consumes it, then Used) or Lift the ban entirely. Replaces the
# old "notify every Manager on every blocked attempt" behavior: Managers now get one notification
# per request instead. Created/decided only through applicant_api.request_country_ban_exception /
# decide_country_ban_request; the pass is consumed in applicant_api._check_country_ban_or_throw.

from frappe.model.document import Document


class CountryBanRequest(Document):
	pass
