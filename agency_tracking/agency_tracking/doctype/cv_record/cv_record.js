// Copyright (c) 2026, Agency and contributors
// License: MIT. See LICENSE

frappe.ui.form.on('CV Record', {
	refresh(frm) {
		if (frm.is_new()) return;

		if (frm.doc.cv_pdf_url) {
			frm.add_custom_button(__('Download CV PDF'), () => {
				window.open(frm.doc.cv_pdf_url);
			}).addClass('btn-primary');
		}

		if (frm.doc.applicant) {
			frm.add_custom_button(__('View Applicant'), () => {
				frappe.set_route('Form', 'Applicant', frm.doc.applicant);
			});
		}
	},
});
