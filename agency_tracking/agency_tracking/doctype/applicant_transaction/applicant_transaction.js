// Copyright (c) 2026, Agency and contributors
// License: MIT. See LICENSE

frappe.ui.form.on('Applicant Transaction', {
	refresh(frm) {
		frm.trigger('setup_custom_buttons');
	},

	setup_custom_buttons(frm) {
		if (frm.is_new()) return;

		if (frm.doc.status === 'Pending') {
			frm.add_custom_button(__('Approve Transaction'), () => {
				frappe.confirm(__('Approve this financial transaction into the general ledger?'), () => {
					frappe.call({
						method: 'agency_tracking.finance_api.approve_transaction',
						args: { transaction_name: frm.doc.name },
						freeze: true,
						freeze_message: __('Approving transaction...'),
						callback(r) {
							if (!r.exc) {
								frappe.show_alert({ message: __('Transaction Approved!'), indicator: 'green' });
								frm.reload_doc();
							}
						},
					});
				});
			}).addClass('btn-primary');

			frm.add_custom_button(__('Reject Transaction'), () => {
				frappe.prompt(
					[{ fieldname: 'reason', fieldtype: 'Small Text', label: __('Rejection Reason'), reqd: 1 }],
					(values) => {
						frappe.call({
							method: 'agency_tracking.finance_api.reject_transaction',
							args: {
								transaction_name: frm.doc.name,
								rejection_reason: values.reason,
							},
							freeze: true,
							freeze_message: __('Rejecting transaction...'),
							callback(r) {
								if (!r.exc) {
									frappe.show_alert({ message: __('Transaction Rejected.'), indicator: 'red' });
									frm.reload_doc();
								}
							},
						});
					},
					__('Reject Transaction'),
					__('Reject')
				);
			}, __('Actions')).addClass('btn-danger');
		}

		if (frm.doc.status === 'Approved') {
			frm.add_custom_button(__('Void Transaction'), () => {
				frappe.prompt(
					[{ fieldname: 'reason', fieldtype: 'Small Text', label: __('Void Reason'), reqd: 1 }],
					(values) => {
						frappe.call({
							method: 'agency_tracking.finance_api.void_transaction',
							args: {
								transaction_name: frm.doc.name,
								void_reason: values.reason,
							},
							freeze: true,
							freeze_message: __('Voiding transaction...'),
							callback(r) {
								if (!r.exc) {
									frappe.show_alert({ message: __('Transaction Voided.'), indicator: 'orange' });
									frm.reload_doc();
								}
							},
						});
					},
					__('Void Transaction'),
					__('Void')
				);
			}, __('Actions'));
		}
	},
});
