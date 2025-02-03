frappe.provide('frappe.tatatele');

frappe.tatatele.CallPopupHandler = class CallPopupHandler {
    constructor() {
        this.activeCall = null;
        this.bindEvents();
    }

    bindEvents() {
        // Listen for incoming call notifications
        frappe.realtime.on('inbound_call_notification', (data) => {
            // Only show popup if not already handling this call
            if (!this.activeCall || this.activeCall.caller_number !== data.caller_number) {
                this.showCallPopup(data);
            }
        });

        // Listen for stop notification event
        frappe.realtime.on('stop_call_notification', (data) => {
            if (this.dialog && this.activeCall && 
                this.activeCall.caller_number === data.caller_number) {
                this.dialog.hide();
                this.activeCall = null;
            }
        });
    }

    showCallPopup(data) {
        if (this.dialog) {
            this.dialog.hide();
        }

        this.activeCall = data;

        this.dialog = new frappe.ui.Dialog({
            title: 'Incoming Call',
            indicator: 'green',
            primary_action_label: 'Accept',
            secondary_action_label: 'Reject',
            fields: [
                {
                    fieldtype: 'HTML',
                    fieldname: 'call_info',
                    options: `
                        <div class="call-popup-content">
                            <div class="call-info-row">
                                <span class="call-label">Caller Number:</span>
                                <span class="call-value">${data.caller_number || 'Unknown'}</span>
                            </div>
                            <div class="call-info-row">
                                <span class="call-label">Lead Name:</span>
                                <span class="call-value">${data.lead_name || 'Unknown'}</span>
                            </div>
                        </div>
                    `
                }
            ],
            primary_action: () => {
                this.handleCallAction('accept', data);
            },
            secondary_action: () => {
                this.handleCallAction('reject', data);
            }
        });

        // Add custom styles
        this.dialog.$wrapper.find('.call-popup-content').css({
            'padding': '15px'
        });

        this.dialog.$wrapper.find('.call-info-row').css({
            'margin-bottom': '10px',
            'display': 'flex',
            'gap': '10px'
        });

        this.dialog.$wrapper.find('.call-label').css({
            'font-weight': 'bold'
        });

        this.dialog.show();

        // Play notification sound
        this.playNotificationSound();
    }

    handleCallAction(action, data) {
        frappe.call({
            method: 'tata_smartflow_onehash_integration.tata_smartflow_onehash_integration.api.calling_api.handle_lead_call_action',
            args: {
                action: action,
                caller_number: data.caller_number
            },
            callback: (response) => {
                if (response.message && response.message.success) {
                    frappe.show_alert({
                        message: response.message.message,
                        indicator: 'green'
                    }, 3);
                    this.dialog.hide();
                    this.activeCall = null;
                } else {
                    frappe.show_alert({
                        message: `Failed to ${action} call`,
                        indicator: 'red'
                    }, 3);
                }
            }
        });
    }

    playNotificationSound() {
        try {
            const audio = new Audio('/assets/tata_smartflow_onehash_integration/sounds/telephone.mp3');
            audio.play();
        } catch (e) {
            console.error('Failed to play notification sound:', e);
        }
    }
}

// Initialize the handler when Frappe is ready
$(document).ready(function() {
    window.call_popup_handler = new frappe.tatatele.CallPopupHandler();
});


