frappe.listview_settings['Tata Tele Users'] = {
    onload: function(listview) {
        // Hide the "Add Subscriber" button
        listview.page.wrapper
            .find('.primary-action')
            .hide();

        // Add the "Fetch Users" button
        listview.page.add_inner_button("Fetch Users", function () {
            fetch_users(listview);
        });

    }
};

function fetch_users(listview) {
    frappe.call({
        method: "tata_smartflow_onehash_integration.tata_smartflow_onehash_integration.api.calling_api.fetch_users",
        callback: function(response) {
            if (response.message.success) {
                let users = response.message.users;
                let skipped = response.message.skipped;
                let saved = response.message.saved;
                
                if (response.message.all_existing) {
                    frappe.show_alert({
                        message: __("No new users to fetch. All users already exist in the system."),
                        indicator: "blue"
                    });
                } else if (users.length > 0) {
                    frappe.show_alert({
                        message: __("Fetched {0} new users successfully. {1} existing users skipped.", [saved, skipped]),
                        indicator: "green"
                    });
                    
                    // Refresh the list view
                    setTimeout(() => {
                        listview.refresh();
                    }, 1000);
                } else if (response.message.message === "No users found in the API response") {
                    frappe.show_alert({
                        message: __("No users found in the API response."),
                        indicator: "orange"
                    });
                } else {
                    frappe.show_alert({
                        message: __("No new users were fetched."),
                        indicator: "orange"
                    });
                }
            } else {
                frappe.show_alert({
                    message: __("Failed to fetch users: {0}", [response.message.message]),
                    indicator: "red"
                });
            }
        },
        freeze: true,
        freeze_message: __("Fetching users...")
    });
}