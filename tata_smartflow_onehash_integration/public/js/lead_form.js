frappe.ui.form.on('Lead', {
    refresh: function(frm) {
        setTimeout(() => {
            
            frm.remove_custom_button('Add to Prospect', 'Action');
            frm.remove_custom_button('Prospect', 'Create'); 
        }, 100);
        
        frm.add_custom_button(__('Call'), function() {
            const phoneNumber = frm.doc.mobile_no || frm.doc.phone || whatsapp_no;

            if (!phoneNumber) {
                frappe.msgprint(__('No phone number found for this lead.'));
                return;
            }
            
            // Example of other actions you can take when the button is clicked:
            // - Send a request
            // - Update the field
            // - Trigger some backend logic
        });

        frm.add_custom_button(__('Hang up Call'), function() {
            frappe.msgprint(__('Button clicked!'));
            
            // Example of other actions you can take when the button is clicked:
            // - Send a request
            // - Update the field
            // - Trigger some backend logic
        });
    }
});
