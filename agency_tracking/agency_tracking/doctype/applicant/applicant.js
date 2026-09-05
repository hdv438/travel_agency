// Copyright (c) 2026, Agency and contributors
// License: MIT. See LICENSE

frappe.ui.form.on('Applicant', {
	refresh(frm) {
		frm.trigger('setup_custom_buttons');
	},

	setup_custom_buttons(frm) {
		if (frm.is_new()) return;

		// --- 1. Passport / OCR Actions ---
		if (frm.doc.passport_scan) {
			frm.add_custom_button(__('Auto-Fill from Passport'), () => {
				frm.trigger('autofill_passport_mrz');
			}, __('Actions'));
		}

		frm.add_custom_button(__('Parse Injaz Paper'), () => {
			frm.trigger('parse_injaz_dialog');
		}, __('Actions'));

		// --- 2. Registration & Lifecycle Actions ---
		if (frm.doc.status === 'Draft') {
			frm.add_custom_button(__('Register Applicant'), () => {
				frm.trigger('register_applicant');
			}).addClass('btn-primary');
		}

		if (frm.doc.status === 'Registered') {
			if (frm.doc.entry_track === 'Standard') {
				frm.add_custom_button(__('Generate CV'), () => {
					frm.trigger('generate_cv');
				}).addClass('btn-primary');
			} else if (frm.doc.entry_track === 'Muayena') {
				frm.add_custom_button(__('Create Muayena Placement'), () => {
					frm.trigger('create_muayena_placement_dialog');
				}).addClass('btn-primary');
			}

			frm.add_custom_button(__('Cancel Applicant'), () => {
				frm.trigger('cancel_applicant_dialog');
			}, __('Actions')).addClass('btn-danger');
		}

		if (frm.doc.status === 'CV Generated') {
			frm.add_custom_button(__('View CV Record'), () => {
				frappe.db.get_value('CV Record', { applicant: frm.doc.name }, 'name').then((r) => {
					if (r && r.message && r.message.name) {
						frappe.set_route('Form', 'CV Record', r.message.name);
					} else {
						frappe.msgprint(__('No CV Record found.'));
					}
				});
			}, __('Actions'));

			frm.add_custom_button(__('Cancel Applicant'), () => {
				frm.trigger('cancel_applicant_dialog');
			}, __('Actions')).addClass('btn-danger');
		}

		if (frm.doc.status === 'Cancelled') {
			frm.add_custom_button(__('Restart (Draft)'), () => {
				frm.trigger('restart_applicant', 'Draft');
			}, __('Actions'));

			frm.add_custom_button(__('Restart (Registered)'), () => {
				frm.trigger('restart_applicant', 'Registered');
			}, __('Actions')).addClass('btn-primary');
		}

		if (frm.doc.active_placement) {
			frm.add_custom_button(__('View Active Placement'), () => {
				frappe.set_route('Form', 'Placement', frm.doc.active_placement);
			}, __('Actions'));
		}

		// --- 3. Registration Fee ---
		if (frm.doc.fee_required && frm.doc.registration_fee_amount && !frm.doc.fee_transaction) {
			frm.add_custom_button(__('Log Fee'), () => {
				frm.trigger('log_applicant_fee');
			}, __('Actions')).addClass('btn-primary');
		}

		if (frm.doc.fee_transaction) {
			frm.add_custom_button(__('View Fee Ledger Entry'), () => {
				frappe.set_route('Form', 'Applicant Transaction', frm.doc.fee_transaction);
			}, __('Actions'));
		}
	},

	log_applicant_fee(frm) {
		frappe.confirm(
			__('Log this registration fee ({0} {1}) into the Finance ledger as Paid?', [
				frm.doc.registration_fee_amount,
				frm.doc.fee_currency || 'ETB',
			]),
			() => {
				frappe.call({
					method: 'agency_tracking.applicant_api.log_applicant_fee',
					args: { applicant_name: frm.doc.name },
					freeze: true,
					freeze_message: __('Logging fee...'),
					callback(r) {
						if (!r.exc) {
							frappe.show_alert({ message: __('Fee logged to the Finance ledger.'), indicator: 'green' });
							frm.reload_doc();
						}
					},
				});
			}
		);
	},

	autofill_passport_mrz(frm) {
		if (!frm.doc.passport_scan) {
			frappe.msgprint(__('Please upload a Passport Scan file first.'));
			return;
		}
		frappe.call({
			method: 'agency_tracking.passport_parser.parse_passport_file',
			args: { file_url: frm.doc.passport_scan },
			freeze: true,
			freeze_message: __('Parsing Passport MRZ...'),
			callback(r) {
				if (r.message && Object.keys(r.message).length > 0) {
					$.each(r.message, (field, val) => {
						if (val && !frm.doc[field]) {
							frm.set_value(field, val);
						}
					});
					frappe.show_alert({
						message: __('Passport data extracted and populated!'),
						indicator: 'green',
					});
				} else {
					frappe.msgprint(__('Could not extract MRZ data from the uploaded scan.'));
				}
			},
		});
	},

	parse_injaz_dialog(frm) {
		new frappe.ui.FileUploader({
			as_dataurl: false,
			allow_multiple: false,
			on_success(file_doc) {
				frappe.call({
					method: 'agency_tracking.contract_parser.parse_injaz_file',
					args: { file_url: file_doc.file_url },
					freeze: true,
					freeze_message: __('Parsing Injaz document...'),
					callback(r) {
						if (r.message && Object.keys(r.message).length > 0) {
							$.each(r.message, (field, val) => {
								if (val && !frm.doc[field]) {
									frm.set_value(field, val);
								}
							});
							frappe.show_alert({
								message: __('Injaz data extracted and populated!'),
								indicator: 'green',
							});
						} else {
							frappe.msgprint(__('No data extracted from Injaz document.'));
						}
					},
				});
			},
		});
	},

	register_applicant(frm) {
		frappe.confirm(
			__('Are you sure you want to Register this applicant?'),
			() => {
				frappe.call({
					method: 'agency_tracking.applicant_api.register_applicant',
					args: { applicant_name: frm.doc.name },
					freeze: true,
					freeze_message: __('Registering applicant...'),
					callback(r) {
						if (!r.exc) {
							frappe.show_alert({
								message: __('Applicant successfully Registered!'),
								indicator: 'green',
							});
							frm.reload_doc();
						}
					},
				});
			}
		);
	},

	generate_cv(frm) {
		frappe.confirm(
			__('Generate official Agency CV document for this applicant?'),
			() => {
				frappe.call({
					method: 'agency_tracking.cv_api.generate_cv',
					args: { applicant_name: frm.doc.name },
					freeze: true,
					freeze_message: __('Generating CV Record & PDF...'),
					callback(r) {
						if (!r.exc) {
							frappe.show_alert({
								message: __('CV Generated successfully!'),
								indicator: 'green',
							});
							frm.reload_doc();
						}
					},
				});
			}
		);
	},

	create_muayena_placement_dialog(frm) {
		let d = new frappe.ui.Dialog({
			title: __('Create Muayena Placement'),
			fields: [
				{
					fieldname: 'contractor',
					fieldtype: 'Link',
					options: 'Contractor',
					label: __('Recruiting Agency / Contractor'),
					reqd: 1,
					get_query() {
						return {
							filters: {
								operating_country: frm.doc.destination_country || '',
							},
						};
					},
				},
				{
					fieldname: 'contract_file',
					fieldtype: 'Attach',
					label: __('Signed Contract (PDF)'),
				},
			],
			primary_action_label: __('Create Placement'),
			primary_action(values) {
				d.hide();
				frappe.call({
					method: 'agency_tracking.placement_api.create_muayena_placement',
					args: {
						applicant_name: frm.doc.name,
						contractor_name: values.contractor,
						file_url: values.contract_file || null,
					},
					freeze: true,
					freeze_message: __('Creating Placement...'),
					callback(r) {
						if (!r.exc && r.message) {
							frappe.show_alert({
								message: __('Muayena Placement created!'),
								indicator: 'green',
							});
							frappe.set_route('Form', 'Placement', r.message.name);
						}
					},
				});
			},
		});
		d.show();
	},

	cancel_applicant_dialog(frm) {
		frappe.prompt(
			[
				{
					fieldname: 'reason',
					fieldtype: 'Small Text',
					label: __('Cancellation Reason'),
					reqd: 1,
				},
			],
			(values) => {
				frappe.call({
					method: 'agency_tracking.applicant_api.cancel_applicant',
					args: {
						applicant_name: frm.doc.name,
						reason: values.reason,
					},
					freeze: true,
					freeze_message: __('Cancelling applicant...'),
					callback(r) {
						if (!r.exc) {
							frappe.show_alert({
								message: __('Applicant Cancelled.'),
								indicator: 'orange',
							});
							frm.reload_doc();
						}
					},
				});
			},
			__('Cancel Applicant'),
			__('Confirm Cancellation')
		);
	},

	restart_applicant(frm, target_status) {
		frappe.confirm(
			__('Restart this Cancelled applicant back to ' + target_status + '?'),
			() => {
				frappe.call({
					method: 'agency_tracking.applicant_api.restart_applicant',
					args: {
						applicant_name: frm.doc.name,
						target_status: target_status,
					},
					freeze: true,
					freeze_message: __('Restarting applicant...'),
					callback(r) {
						if (!r.exc) {
							frappe.show_alert({
								message: __('Applicant restarted as ' + target_status + '!'),
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
