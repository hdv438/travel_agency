// Copyright (c) 2026, Agency and contributors
// License: MIT. See LICENSE

frappe.ui.form.on('Clearance Step', {
	refresh(frm) {
		frm.trigger('setup_custom_buttons');
	},

	setup_custom_buttons(frm) {
		if (frm.is_new()) return;

		const is_embassy = ['Embassy', 'Kuwait Embassy'].includes(frm.doc.step_type);

		if (is_embassy) {
			if (frm.doc.status === 'Pending') {
				frm.add_custom_button(__('Submit to Embassy'), () => {
					frm.trigger('submit_embassy');
				}).addClass('btn-primary');
			}
			if (frm.doc.status === 'Submitted') {
				frm.add_custom_button(__('Stamp Embassy Step'), () => {
					frm.trigger('stamp_embassy');
				}).addClass('btn-primary');

				frm.add_custom_button(__('Reject Embassy Step'), () => {
					frm.trigger('reject_embassy');
				}, __('Actions')).addClass('btn-danger');
			}
		} else {
			if (frm.doc.status === 'Pending') {
				frm.add_custom_button(__('Start Step'), () => {
					frm.trigger('start_step');
				}, __('Actions'));
			}
			if (['Pending', 'In Progress'].includes(frm.doc.status)) {
				frm.add_custom_button(__('Complete Step'), () => {
					frm.trigger('complete_step_dialog');
				}).addClass('btn-primary');
			}
		}

		// Reassign option for Manager/Admin
		if (frappe.user_roles.includes('Manager') || frappe.user_roles.includes('Administrator')) {
			frm.add_custom_button(__('Reassign Officer'), () => {
				frm.trigger('reassign_dialog');
			}, __('Actions'));
		}
	},

	start_step(frm) {
		frappe.call({
			method: 'agency_tracking.clearance_api.start_clearance_step',
			args: { clearance_step_name: frm.doc.name },
			freeze: true,
			freeze_message: __('Starting clearance step...'),
			callback(r) {
				if (!r.exc) {
					frappe.show_alert({ message: __('Step started!'), indicator: 'green' });
					frm.reload_doc();
				}
			},
		});
	},

	complete_step_dialog(frm) {
		let d = new frappe.ui.Dialog({
			title: __('Complete Clearance Step'),
			fields: [
				{
					fieldname: 'reference_no',
					fieldtype: 'Data',
					label: __('Reference / Tracking / Certificate #'),
				},
				{
					fieldname: 'amount',
					fieldtype: 'Currency',
					label: __('Cost / Fee Amount (if paid)'),
				},
			],
			primary_action_label: __('Mark Complete'),
			primary_action(values) {
				d.hide();
				frappe.call({
					method: 'agency_tracking.clearance_api.complete_clearance_step',
					args: {
						clearance_step_name: frm.doc.name,
						reference_no: values.reference_no || null,
						amount: values.amount || null,
					},
					freeze: true,
					freeze_message: __('Completing step...'),
					callback(r) {
						if (!r.exc) {
							frappe.show_alert({ message: __('Step completed!'), indicator: 'green' });
							frm.reload_doc();
						}
					},
				});
			},
		});
		d.show();
	},

	submit_embassy(frm) {
		frappe.confirm(__('Submit documents to Embassy?'), () => {
			frappe.call({
				method: 'agency_tracking.clearance_api.submit_embassy_step',
				args: { clearance_step_name: frm.doc.name },
				freeze: true,
				freeze_message: __('Submitting to embassy...'),
				callback(r) {
					if (!r.exc) {
						frappe.show_alert({ message: __('Documents marked Submitted!'), indicator: 'green' });
						frm.reload_doc();
					}
				},
			});
		});
	},

	stamp_embassy(frm) {
		frappe.prompt(
			[{ fieldname: 'reference_no', fieldtype: 'Data', label: __('Visa / Stamp Reference #') }],
			(values) => {
				frappe.call({
					method: 'agency_tracking.clearance_api.stamp_embassy_step',
					args: {
						clearance_step_name: frm.doc.name,
						reference_no: values.reference_no || null,
					},
					freeze: true,
					freeze_message: __('Recording stamped visa...'),
					callback(r) {
						if (!r.exc) {
							frappe.show_alert({ message: __('Visa Stamped!'), indicator: 'green' });
							frm.reload_doc();
						}
					},
				});
			},
			__('Record Stamped Visa'),
			__('Confirm Stamped')
		);
	},

	reject_embassy(frm) {
		frappe.prompt(
			[{ fieldname: 'rejection_remark', fieldtype: 'Small Text', label: __('Rejection Reason / Remark'), reqd: 1 }],
			(values) => {
				frappe.call({
					method: 'agency_tracking.clearance_api.reject_embassy_step',
					args: {
						clearance_step_name: frm.doc.name,
						rejection_remark: values.rejection_remark,
					},
					freeze: true,
					freeze_message: __('Recording embassy rejection...'),
					callback(r) {
						if (!r.exc) {
							frappe.show_alert({ message: __('Embassy Rejection recorded.'), indicator: 'red' });
							frm.reload_doc();
						}
					},
				});
			},
			__('Record Embassy Rejection'),
			__('Confirm Rejection')
		);
	},

	reassign_dialog(frm) {
		frappe.prompt(
			[{ fieldname: 'new_officer', fieldtype: 'Link', options: 'User', label: __('Assign To Officer'), reqd: 1 }],
			(values) => {
				frappe.call({
					method: 'agency_tracking.clearance_api.reassign_clearance_step',
					args: {
						clearance_step_name: frm.doc.name,
						new_officer: values.new_officer,
					},
					freeze: true,
					freeze_message: __('Reassigning officer...'),
					callback(r) {
						if (!r.exc) {
							frappe.show_alert({ message: __('Step reassigned!'), indicator: 'green' });
							frm.reload_doc();
						}
					},
				});
			},
			__('Reassign Clearance Step'),
			__('Reassign')
		);
	},
});
