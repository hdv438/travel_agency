// Copyright (c) 2026, Agency and contributors
// License: MIT. See LICENSE

frappe.ui.form.on('Complaint', {
	refresh(frm) {
		frm.trigger('setup_custom_buttons');
	},

	setup_custom_buttons(frm) {
		if (frm.is_new()) return;

		if (frm.doc.status === 'New') {
			frm.add_custom_button(__('Acknowledge Complaint'), () => {
				frappe.call({
					method: 'agency_tracking.complaint_api.acknowledge_complaint',
					args: { complaint_name: frm.doc.name },
					freeze: true,
					freeze_message: __('Acknowledging complaint...'),
					callback(r) {
						if (!r.exc) {
							frappe.show_alert({ message: __('Complaint Acknowledged (Unresolved)'), indicator: 'blue' });
							frm.reload_doc();
						}
					},
				});
			}).addClass('btn-primary');
		}

		if (frm.doc.status === 'Unresolved') {
			frm.add_custom_button(__('Resolve (Satisfied)'), () => {
				frm.trigger('resolve_dialog', 'Resolved');
			}).addClass('btn-primary');

			frm.add_custom_button(__('Free Replacement Required'), () => {
				frm.trigger('resolve_dialog', 'Returned - Free Replacement Required');
			}, __('Actions')).addClass('btn-warning');

			frm.add_custom_button(__('Escalate'), () => {
				frm.trigger('resolve_dialog', 'Escalated');
			}, __('Actions'));

			frm.add_custom_button(__('Dismiss'), () => {
				frm.trigger('resolve_dialog', 'Dismissed');
			}, __('Actions')).addClass('btn-danger');
		}
	},

	resolve_dialog(frm, target_status) {
		let fields = [
			{
				fieldname: 'resolution_notes',
				fieldtype: 'Small Text',
				label: __('Resolution Notes / Written Reason'),
				reqd: target_status === 'Dismissed' ? 1 : 0,
			},
		];

		if (target_status === 'Returned - Free Replacement Required') {
			fields.push({
				fieldname: 'override_reason',
				fieldtype: 'Data',
				label: __('Manager Override Reason (if past 90 days)'),
			});
		}

		let d = new frappe.ui.Dialog({
			title: __('Resolve Complaint: ') + target_status,
			fields: fields,
			primary_action_label: __('Apply Resolution'),
			primary_action(values) {
				d.hide();
				frappe.call({
					method: 'agency_tracking.complaint_api.resolve_complaint',
					args: {
						complaint_name: frm.doc.name,
						new_status: target_status,
						resolution_notes: values.resolution_notes || null,
						override_reason: values.override_reason || null,
					},
					freeze: true,
					freeze_message: __('Applying resolution...'),
					callback(r) {
						if (!r.exc) {
							frappe.show_alert({ message: __('Complaint updated to ' + target_status), indicator: 'green' });
							frm.reload_doc();
						}
					},
				});
			},
		});
		d.show();
	},
});
