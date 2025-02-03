frappe.ui.form.on('Lead', {
    refresh: function (frm) {
        // Delay removal of custom buttons to ensure they are rendered first
        setTimeout(() => {
            frm.remove_custom_button('Add to Prospect', 'Action');
            frm.remove_custom_button('Prospect', 'Create');
        }, 100);

        // Add "Call" custom button
        frm.add_custom_button(__('Call'), function () {

            const phoneNumber = frm.doc.mobile_no || frm.doc.phone || frm.doc.whatsapp_no;

            if (!phoneNumber) {
                frappe.msgprint(__('No phone number found for this lead.'));
                return;
            }

            frappe.prompt([
                {
                    fieldname: 'agent_name',
                    label: __('Agent Name'),
                    fieldtype: 'Link',
                    options: 'Tata Tele Users',
                    reqd: 1
                },
                {
                    fieldname: 'client_number',
                    label: __('Client Number'),
                    fieldtype: 'Data',
                    default: phoneNumber,
                    read_only: 1
                }], function (values) {
                    frappe.call({
                        method: "frappe.client.get_value",
                        args: {
                            doctype: "Tata Tele Users",
                            filters: { name: values.agent_name },
                            fieldname: ["phone_number"]
                        },
                        callback: function (response) {
                            const agentPhoneNumber = response.message.phone_number;

                            if (!agentPhoneNumber) {
                                frappe.msgprint(__('No phone number found for the selected agent.'));
                                return;
                            }

                            // Call the backend API
                            frappe.call({
                                method: "tata_smartflow_onehash_integration.tata_smartflow_onehash_integration.api.calling_api.initiate_call",
                                args: {
                                    docname: frm.doc.name,
                                    agent_name: values.agent_name,
                                    client_phone_number: values.client_number
                                },
                                callback: function (response) {
                                    if (response.message) {
                                        frappe.show_alert({
                                            message: __("Call Inititated"),
                                            indicator: "green"
                                        });
                                    } else {
                                        frappe.show_alert({
                                            message: __("Failed to initiate call"),
                                            indicator: "orange"
                                        });
                                    }
                                },
                                error: function () {
                                    frappe.show_alert({
                                        message: __("An error occurred while initiating the call"),
                                        indicator: "red"
                                    });
                                }
                            });
                        }
                    });
                }, __('Initiate Call'), __('Call Now'));
        });

        // Add "Hang up Call" custom button
        // if (frm.doc.call_id) {
        //     frm.add_custom_button(__('Hang up Call'), function () {
        //         frappe.confirm(
        //             __('Are you sure you want to hang up this call?'),
        //             function() {
        //                 // Yes
        //                 frappe.call({
        //                     method: "tata_smartflow_onehash_integration.tata_smartflow_onehash_integration.api.calling_api.hangup_call",
        //                     args: {
        //                         docname: frm.doc.name
        //                     },
        //                     callback: function(response) {
        //                         if (response.message && response.message.success) {
        //                             frappe.show_alert({
        //                                 message: __("Call hung up successfully"),
        //                                 indicator: "green"
        //                             });
        //                             frm.reload_doc(); // Reload to clear call_id
        //                         } else {
        //                             frappe.show_alert({
        //                                 message: __("Failed to hang up call: " + (response.message.message || "")),
        //                                 indicator: "orange"
        //                             });
        //                         }
        //                     },
        //                     error: function() {
        //                         frappe.show_alert({
        //                             message: __("An error occurred while hanging up the call"),
        //                             indicator: "red"
        //                         });
        //                     }
        //                 });
        //             }
        //         );
        //     }, __('Call'));
        // }
    }
});
