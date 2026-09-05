// Copyright (c) 2026, Agency and contributors
// License: MIT. See LICENSE

frappe.ui.form.on('Placement', {
	refresh(frm) {
		frm.trigger('setup_custom_buttons');
	},

	setup_custom_buttons(frm) {
		if (frm.is_new()) return;

		// --- 1. Document Parsing Actions ---
		frm.add_custom_button(__('Upload & Parse Contract'), () => {
			frm.trigger('upload_contract_dialog');
		}, __('Documents'));

		if (frm.doc.destination_country === 'Kuwait') {
			frm.add_custom_button(__('Upload & Parse eVisa'), () => {
				frm.trigger('upload_visa_dialog');
			}, __('Documents'));
		}

		// --- 2. Stage Progression Actions ---
		if (frm.doc.status === 'Selected') {
			frm.add_custom_button(__('Record Medical Result'), () => {
				frm.trigger('record_selected_medical_dialog');
			}, __('Actions'));

			frm.add_custom_button(__('Advance to Processing'), () => {
				frm.trigger('advance_status', 'Processing');
			}).addClass('btn-primary');
		}

		if (frm.doc.status === 'Processing') {
			frm.add_custom_button(__('Advance to Stamped'), () => {
				frm.trigger('advance_status', 'Stamped');
			}).addClass('btn-primary');
		}

		if (frm.doc.status === 'Stamped') {
			frm.add_custom_button(__('Record Ticketing & Advance'), () => {
				frm.trigger('record_ticket_dialog');
			}).addClass('btn-primary');
		}

		if (frm.doc.status === 'Ticketed') {
			frm.add_custom_button(__('Record Medical 2 Result'), () => {
				frm.trigger('record_medical_2_dialog');
			}, __('Actions'));

			frm.add_custom_button(__('Advance to Departed'), () => {
				frm.trigger('advance_status', 'Departed');
			}).addClass('btn-primary');
		}

		// Quick link to Clearance Steps
		frm.add_custom_button(__('View Clearance Steps'), () => {
			frappe.set_route('List', 'Clearance Step', { placement: frm.doc.name });
		}, __('Actions'));
	},

	upload_contract_dialog(frm) {
		new frappe.ui.FileUploader({
			as_dataurl: false,
			allow_multiple: false,
			on_success(file_doc) {
				frappe.call({
					method: 'agency_tracking.placement_api.upload_contract',
					args: {
						placement_name: frm.doc.name,
						file_url: file_doc.file_url,
					},
					freeze: true,
					freeze_message: __('Parsing Contract PDF...'),
					callback(r) {
						if (!r.exc) {
							frappe.show_alert({
								message: __('Contract parsed and saved!'),
								indicator: 'green',
							});
							frm.reload_doc();
						}
					},
				});
			},
		});
	},

	upload_visa_dialog(frm) {
		new frappe.ui.FileUploader({
			as_dataurl: false,
			allow_multiple: false,
			on_success(file_doc) {
				frappe.call({
					method: 'agency_tracking.placement_api.upload_visa',
					args: {
						placement_name: frm.doc.name,
						file_url: file_doc.file_url,
					},
					freeze: true,
					freeze_message: __('Parsing eVisa PDF...'),
					callback(r) {
						if (!r.exc) {
							frappe.show_alert({
								message: __('eVisa parsed and saved!'),
								indicator: 'green',
							});
							frm.reload_doc();
						}
					},
				});
			},
		});
	},

	record_selected_medical_dialog(frm) {
		let d = new frappe.ui.Dialog({
			title: __('Record Selected Medical Result'),
			fields: [
				{
					fieldname: 'status',
					fieldtype: 'Select',
					options: 'FIT
UNFIT',
					default: 'FIT',
					label: __('Medical Result'),
					reqd: 1,
				},
				{
					fieldname: 'examination_date',
					fieldtype: 'Date',
					label: __('Examination Date'),
					default: frappe.datetime.nowdate(),
				},
				{
					fieldname: 'expiry_date',
					fieldtype: 'Date',
					label: __('Expiry Date'),
				},
			],
			primary_action_label: __('Save Result'),
			primary_action(values) {
				d.hide();
				frappe.call({
					method: 'agency_tracking.placement_api.record_selected_medical_result',
					args: {
						placement_name: frm.doc.name,
						status: values.status,
						examination_date: values.examination_date,
						expiry_date: values.expiry_date,
					},
					freeze: true,
					freeze_message: __('Recording medical result...'),
					callback(r) {
						if (!r.exc) {
							frappe.show_alert({
								message: __('Medical result recorded!'),
								indicator: values.status === 'FIT' ? 'green' : 'red',
							});
							frm.reload_doc();
						}
					},
				});
			},
		});
		d.show();
	},

	record_medical_2_dialog(frm) {
		frappe.prompt(
			[
				{
					fieldname: 'status',
					fieldtype: 'Select',
					options: 'FIT
UNFIT',
					default: 'FIT',
					label: __('Pre-Departure Medical (Medical 2) Result'),
					reqd: 1,
				},
			],
			(values) => {
				frm.set_value('medical_2_status', values.status);
				frm.save();
			},
			__('Record Medical 2 Result'),
			__('Save')
		);
	},

	record_ticket_dialog(frm) {
		let d = new frappe.ui.Dialog({
			title: __('Record Flight Ticket Details'),
			fields: [
				{
					fieldname: 'ticket_number',
					fieldtype: 'Data',
					label: __('Ticket / E-Ticket Number'),
					reqd: 1,
				},
				{
					fieldname: 'flight_date',
					fieldtype: 'Datetime',
					label: __('Flight Date & Time'),
					reqd: 1,
				},
				{
					fieldname: 'ticket_cost',
					fieldtype: 'Currency',
					label: __('Ticket Cost'),
				},
			],
			primary_action_label: __('Record & Advance to Ticketed'),
			primary_action(values) {
				d.hide();
				frappe.call({
					method: 'agency_tracking.placement_api.record_ticket_details',
					args: {
						placement_name: frm.doc.name,
						ticket_number: values.ticket_number,
						flight_date: values.flight_date,
						ticket_cost: values.ticket_cost || null,
					},
					freeze: true,
					freeze_message: __('Saving ticket details...'),
					callback(r) {
						if (!r.exc) {
							// Advance placement to Ticketed
							frappe.call({
								method: 'agency_tracking.placement_api.advance_placement',
								args: {
									placement_name: frm.doc.name,
									new_status: 'Ticketed',
								},
								callback(res) {
									if (!res.exc) {
										frappe.show_alert({
											message: __('Placement advanced to Ticketed!'),
											indicator: 'green',
										});
										frm.reload_doc();
									}
								},
							});
						}
					},
				});
			},
		});
		d.show();
	},

	advance_status(frm, target_status) {
		frappe.confirm(
			__('Advance this Placement to ' + target_status + '?'),
			() => {
				frappe.call({
					method: 'agency_tracking.placement_api.advance_placement',
					args: {
						placement_name: frm.doc.name,
						new_status: target_status,
					},
					freeze: true,
					freeze_message: __('Advancing to ' + target_status + '...'),
					callback(r) {
						if (!r.exc) {
							frappe.show_alert({
								message: __('Placement is now ' + target_status + '!'),
								indicator: 'green',
							});
							frm.reload_doc();
						}
					},
				});
			}
		);
	},
});
