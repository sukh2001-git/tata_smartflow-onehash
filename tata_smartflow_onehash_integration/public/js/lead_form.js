frappe.ui.form.on('Lead', {
    refresh: function (frm) {
        // Delay removal of custom buttons to ensure they are rendered first
        setTimeout(() => {
            frm.remove_custom_button('Add to Prospect', 'Action');
            frm.remove_custom_button('Prospect', 'Create');
        }, 100);

        // Add "Call" custom button
        frm.add_custom_button(__('Call'), function () {
            frappe.msgprint("Clicked on Call button!");

            const phoneNumber = frm.doc.mobile_no || frm.doc.phone || frm.doc.whatsapp_no;

            if (!phoneNumber) {
                frappe.msgprint(__('No phone number found for this lead.'));
                return;
            }

            // Call the backend API
            frappe.call({
                method: "tata_smartflow_onehash_integration.tata_smartflow_onehash_integration.api.calling_api.initiate_call",
                args: {
                    docname: frm.doc.name,
                },
                callback: function (response) {
                    if (response.message) {
                        frappe.msgprint(__('Call initiated successfully!'));
                    } else {
                        frappe.msgprint(__('Failed to initiate the call.'));
                    }
                },
                error: function () {
                    frappe.msgprint(__('An error occurred while initiating the call.'));
                }
            });
        });

        // Add "Hang up Call" custom button
        frm.add_custom_button(__('Hang up Call'), function () {
            frappe.msgprint(__('Hang up button clicked!'));

        });
    }
});
