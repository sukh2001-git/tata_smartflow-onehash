import frappe
import http.client
import json
from frappe import _
from frappe.utils import now

@frappe.whitelist(allow_guest=True)
def fetch_call_records():
    try:    
        # Get settings from Custom DocType
        settings = frappe.get_single("Tata Tele API Cloud Settings")
        if not settings:
            return {
                "success": False,
                "message": "Tata Tele API Cloud Settings not configured correctly"
            }
            
        # Get decrypted auth token
        auth_token = frappe.utils.password.get_decrypted_password(
            "Tata Tele API Cloud Settings",
            "Tata Tele API Cloud Settings",
            "api_token"
        )
        
        # Prepare API call
        base_url = settings.url
        endpoint = "/v1/call/records"
        
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "Authorization": auth_token
        }
        
        conn = http.client.HTTPSConnection(base_url)
        conn.request(
            "GET",
            endpoint,
            headers=headers
        )
        
        # Make API call using http.client
        conn = http.client.HTTPSConnection(base_url)
        conn.request("GET", endpoint, headers=headers)
        response = conn.getresponse()
        response_data = json.loads(response.read().decode("utf-8"))
        
        frappe.log_error("call response data is", response_data)
        
        if response.status == 200 and "results" in response_data:
            for call in response_data["results"]:
                # Create or update call log
                call_log = create_call_log(call)
                
                # Update missed agents if present
                if call.get("missed_agents"):
                    insert_missed_agents(call_log.name, call["missed_agents"])
                    
                # Update hangup records if present
                if call.get("agent_hangup_data"):
                    insert_hangup_records(call_log.name, call["agent_hangup_data"])
                
            return {
                "success": True,
                "message": "Call records processed successfully"
            }
        else:
            return {
                "success": False,
                "message": f"Failed to fetch tata tele call records: {response_data.get('message', 'Unknown error')}"
            }
            
    except Exception as e:
        return {
            "success": False,
            "message": f"Error: {str(e)}"
        }
    finally:
        if 'conn' in locals():
            conn.close()
            
def format_phone_number(phone_number):
    """Remove plus sign from phone number if present, keeping country code"""
    if phone_number.startswith("+"):
        return phone_number[1:]
    return phone_number

def format_agent_number(phone_number):
    if not phone_number:
        return phone_number
    
    phone_number = phone_number.strip()
    
    if phone_number.startswith('+91'):
        phone_number = phone_number[3:]   
        
    return phone_number
        
             
# Helping functions for fetch_call_records method       
def create_call_log(call_data):
    """Create or update call log entry"""
    existing_log = frappe.get_all(
        "Tata Tele Call Logs",
        filters={"call_id": call_data["call_id"]},
        limit=1
    )
    
    formatted_number = format_phone_number(call_data["client_number"])
    formatted_agent_number = format_agent_number(call_data["agent_number"])
    
    call_doc = frappe.get_doc({
        "doctype": "Tata Tele Call Logs",
        "call_id": call_data["call_id"],
        "agent_name": call_data["agent_name"],
        "call_type": "Inbound" if call_data["direction"] == "inbound" else "Outbound",
        "call_date": call_data["date"],
        "call_time": call_data["time"],
        "last_entry_time": call_data["end_stamp"],
        "duration": call_data["call_duration"],
        "customer_number": formatted_number,
        "status": call_data["status"].capitalize(),
        "recording_url": call_data.get("recording_url"),
        "description": call_data["description"],
        "agent_phone_number": formatted_agent_number
    })
    
    if existing_log:
        call_doc.name = existing_log[0].name
        call_doc.save()
    else:
        call_doc.insert(ignore_permissions=True)
        
    return call_doc

def insert_missed_agents(call_log_name, missed_agents):
    """Update missed agents for a call log"""
    call_doc = frappe.get_doc("Tata Tele Call Logs", call_log_name)
    call_doc.missed_agents = []
    
    for agent in missed_agents:
        call_doc.append("missed_agents", {
            "agent_name": agent["name"],
            "number": agent["number"]
        })
    
    call_doc.save()

def insert_hangup_records(call_log_name, hangup_data):
    """Update hangup records for a call log"""
    call_doc = frappe.get_doc("Tata Tele Call Logs", call_log_name)
    call_doc.hang_up_call_records = []
    
    for record in hangup_data:
        call_doc.append("hang_up_call_records", {
            "id": record["id"],
            "agent_name": record["name"],
            "agent_id": record["id"],
            "disposition": record["disposition"],
        })
    
    call_doc.save()
    
    


@frappe.whitelist()
def fetch_users():
    try:
        # Get settings from Custom DocType
        settings = frappe.get_single("Tata Tele API Cloud Settings")
        if not settings:
            return {
                "success": False,
                "message": "Tata Tele API Cloud Settings not configured correctly"
            }

        # Get decrypted auth token
        auth_token = frappe.utils.password.get_decrypted_password(
            "Tata Tele API Cloud Settings",
            "Tata Tele API Cloud Settings",
            "api_token"
        )

        # Prepare API call
        base_url = settings.url
        endpoint = "/v1/users"  

        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "Authorization": f"Bearer {auth_token}"
        }

        # Make API call using http.client
        conn = http.client.HTTPSConnection(base_url)
        conn.request("GET", endpoint, headers=headers)
        response = conn.getresponse()

        # Check if the API call was successful
        if response.status != 200:
            return {
                "success": False,
                "message": f"Failed to fetch users. Status Code: {response.status}, Reason: {response.reason}"
            }

        # Parse the response data
        response_data = json.loads(response.read().decode("utf-8"))
        
        frappe.log_error("response data", response_data)

        saved_users = []
        skipped_users = []
        
        status_map = {
            0: "Enabled",
            1: "Blocked",
            2: "Disabled"
        }
        
        # Map the API response to the required fields
        api_users = response_data.get("data", [])
        
        if not api_users:
            return {
                "success": True,
                "message": "No users found in the API response",
                "users": [],
                "skipped": 0,
                "saved": 0,
                "all_existing": False
            }
            
        def clean_phone_number(phone):
            """Clean phone number to get 10 digits only"""
            if not phone:
                return None
            # Remove +91 or 91 prefix and any non-digit characters
            cleaned = ''.join(filter(str.isdigit, phone))
            if cleaned.startswith('91') and len(cleaned) > 10:
                cleaned = cleaned[2:]
            return cleaned[-10:] if len(cleaned) >= 10 else cleaned
        
        
        def find_erp_user(phone_number):
            """Find ERP user by mobile number and return email"""
            if not phone_number:
                return None
            user = frappe.get_all(
                "User",
                filters={"mobile_no": phone_number},
                fields=["name"],
                limit=1
            )
            return user[0].name if user else None
        
        # Map the API response to the required fields
        for user in api_users:
            # Check if user already exists
            existing_user = frappe.get_all(
                "Tata Tele Users",
                filters={"id": user.get("id")},
                fields=["agent_name", "phone_number"]
            )
            
            if existing_user:
                # Skip existing users
                skipped_users.append(user.get("id"))
                continue
            
            agent_data = user.get("agent", {})
            user_role = user.get("user_role", {})  
            
            numeric_status = agent_data.get("status")
            status_text = status_map.get(numeric_status)
            
            clean_phone = clean_phone_number(agent_data.get("follow_me_number"))
            erp_user = find_erp_user(clean_phone)
            
            # Prepare user data for new users
            user_data = {
                "doctype": "Tata Tele Users",
                "id": user.get("id"),
                "agent_name": agent_data.get("name"),
                "phone_number": clean_phone,
                "login_id": user.get("login_id"),
                "status": status_text,
                "role": user_role.get("name"),
                "login_based_calling_enabled": user.get("is_login_based_calling_enabled"),
                "international_outbound_enabled": user.get("is_international_outbound_enabled"),
                "agent_number": agent_data.get("id"),
                "user": erp_user
            }
            
            frappe.log_error("user data", user_data)
            
            try:
                # Create new user
                doc = frappe.get_doc(user_data)
                doc.insert()
                
                saved_users.append({
                    "id": user.get("id"),
                    "agent_name": agent_data.get("name"),
                    "phone_number": clean_phone,
                    "login_id": user.get("login_id"),
                    "status": status_text,
                    "role": user_role.get("name"),
                    "login_based_calling_enabled": user.get("is_login_based_calling_enabled"),
                    "international_outbound_enabled": user.get("is_international_outbound_enabled"),
                    "agent_number": agent_data.get("id"),
                    "erp_user": erp_user
                })
            except Exception as e:
                frappe.log_error(
                    frappe.get_traceback(),
                    f"Failed to save user {user.get('id')}"
                )
        
        # Check if all users were skipped (all existing)
        all_existing = len(skipped_users) == len(api_users)
        
        # Return the fetched users with additional context
        return {
            "success": True,
            "users": saved_users,
            "skipped": len(skipped_users),
            "saved": len(saved_users),
            "all_existing": all_existing,
            "message": "All users already exist in the system" if all_existing else None
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), _("Failed to fetch users"))
        return {
            "success": False,
            "message": f"An error occurred: {str(e)}"
        }
        
# @frappe.whitelist()
# def add_user():
#     try:
#         pass
#     except Exception as e:
#         frappe.log_error(frappe.get_traceback(), _("Failed to add user"))
        
@frappe.whitelist()
def initiate_call(docname, agent_name, client_phone_number):
    try:
        frappe.log_error("i am heree")
        # Get settings from Custom DocType
        settings = frappe.get_single("Tata Tele API Cloud Settings")
        if not settings:
            return {
                "success": False,   
                "message": "Tata Tele API Cloud Settings not configured correctly"
            }
            
        # Prepare API call
        base_url = settings.url
        endpoint = "/v1/click_to_call"
        
        agent_details = frappe.get_value("Tata Tele Users", 
            agent_name, 
            ['id', "agent_number"], 
            as_dict=1)
        
        frappe.log_error("agent detail", agent_details)
        
        auth_token = frappe.utils.password.get_decrypted_password(
            "Tata Tele API Cloud Settings",
            "Tata Tele API Cloud Settings",
            "api_token"
        )
        
        frappe.log_error("auth_token", auth_token)
        
        # Prepare request payload
        payload = {
            "agent_number": agent_details.agent_number,
            "destination_number": client_phone_number,
            "caller_id": settings.did_number,  
            "async": 1,
            "get_call_id": 1
        }

        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "Authorization": auth_token
        }
        
        frappe.log_error("headers", headers)

        # Make API call using http.client
        conn = http.client.HTTPSConnection(base_url)
        conn.request(
            "POST",
            endpoint,
            body=json.dumps(payload),
            headers=headers
        )

        # Get response
        response = conn.getresponse()
        response_data = json.loads(response.read().decode("utf-8"))

        # Log the response for debugging
        frappe.log_error("response_data", response_data)
        
        if response_data.get("success") == True:
            lead_doc = frappe.get_doc("Lead", docname)
            frappe.log_error("lead doc", lead_doc)
            lead_doc.call_id = response_data.get("call_id")
            lead_doc.save(ignore_permissions=True)

        return {
            "success": True,
            "message": "Call initiated successfully",
        }

    except Exception as e:
        frappe.logger().error(f"Click to call error: {str(e)}")
        return {
            "success": False,
            "message": f"Failed to initiate call: {str(e)}"
        }
        
@frappe.whitelist()
def hangup_call(docname):
    try:
        # Get the Lead document
        lead_doc = frappe.get_doc("Lead", docname)
        
        # Get settings and make hangup API call
        settings = frappe.get_single("Tata Tele API Cloud Settings")
        
        auth_token = frappe.utils.password.get_decrypted_password(
            "Tata Tele API Cloud Settings",
            "Tata Tele API Cloud Settings",
            "api_token"
        )
        base_url = settings.url
        endpoint = "/v1/hangup_call"  
        
        # Prepare hangup request payload
        payload = {
            "call_id": lead_doc.call_id
        }
        
        # Make API call to hangup
        conn = http.client.HTTPSConnection(base_url)
        conn.request(
            "POST",
            endpoint,
            body=json.dumps(payload),
            headers={
                "accept": "application/json",
                "content-type": "application/json",
                "Authorization": auth_token
            }
        )
        
        response = conn.getresponse()
        response_data = json.loads(response.read().decode("utf-8"))
        
        if response_data.get("success") == True:
            # Clear the call_id field
            lead_doc.call_id = ""
            lead_doc.save(ignore_permissions=True)
            
            return {
                "success": True,
                "message": "Call hung up successfully"
            }
        else:
            return {
                "success": False,
                "message": "Failed to hang up call"
            }
            
    except Exception as e:
        frappe.log_error(f"Hangup call error: {str(e)}")
        return {
            "success": False,
            "message": f"Failed to hang up call: {str(e)}"
        }
        
@frappe.whitelist()
def handle_inbound_call():
    try:
        if not frappe.request or not frappe.request.data:
            frappe.throw(_("No data received"))
            
        data = json.loads(frappe.request.data)
        frappe.log_error("Inbound lead call data", data)
        
        # Get settings
        settings = frappe.get_single("Tata Tele API Cloud Settings")
        if not settings:
            frappe.throw(_("Tata Tele API Cloud Settings not configured"))
        
        # Find matching lead using get_list
        leads = frappe.get_list("Lead", 
            filters={"mobile_no": data.get("caller_id_number")},
            fields=["name", "first_name", "mobile_no"]
        )
        
        
        if leads:
            lead = leads[0]  # Get first matching lead
            
            # Send notification with lead info
            notification_data = {
                "caller_number": data.get("caller_id_number"),
                "lead_number": lead.mobile_no,
                "lead_name": lead.first_name,
                "lead_id": lead.name 
            }
            
            frappe.get_doc("Lead", lead.name).add_comment(
                "Info",
                f"Incoming call received from {data.get('caller_id_number')}"
            )
            
            frappe.publish_realtime(
                event='inbound_call_notification',
                message=notification_data,
                user=frappe.session.user
            )
            
            return {
                "success": True,
                "message": "Lead call notification sent successfully"
            }
        
        return {
            "success": False,
            "message": "No matching lead found"
        }
            
    except Exception as e:
        frappe.logger().error(f"Inbound lead call error: {str(e)}")
        return {
            "success": False,
            "message": f"Failed to process inbound call: {str(e)}"
        }

# @frappe.whitelist()
# def handle_lead_call_action(action, caller_number, lead=None):
#     """Handle call accept/reject action for leads"""
#     try:
#         # Find the lead based on caller number
#         leads = frappe.get_list("Lead", 
#             filters={"mobile_no": caller_number},
#             fields=["name", "first_name", "mobile_no"]
#         )
        
#         if not leads:
#             return {
#                 "success": False,
#                 "message": "No lead found"
#             }
            
#         lead = leads[0]
        
#         # Add comment to lead
#         frappe.get_doc("Lead", lead.name).add_comment(
#             "Info",
#             f"Incoming call was {action}ed"
#         )
        
#         # Send event to stop the notification
#         frappe.publish_realtime(
#             event='stop_call_notification',
#             message={"caller_number": caller_number},
#             user=frappe.session.user
#         )
        
#         return {
#             "success": True,
#             "message": f"Call {action}ed successfully"
#         }
            
#     except Exception as e:
#         frappe.logger().error(f"Lead call action error: {str(e)}")
#         return {
#             "success": False,
#             "message": str(e)
#         }       
        
        
def sync_call_records():
    """
    Sync call records from Tata Tele Call Logs to Lead's calling history
    """
    # Get all leads with mobile numbers
    leads = frappe.get_all(
        "Lead",
        filters={"mobile_no": ["!=", ""]},
        fields=["name", "mobile_no"]
    )
    
    frappe.log_error("leads are:", leads)
    
    for lead in leads:
        # Search for call records in Tata Tele Call Logs
        call_logs = frappe.get_all(
            "Tata Tele Call Logs",
            filters={
                "customer_number": lead.mobile_no
            },
            fields=[
                "call_id",
                "agent_name",
                "call_type",
                "status",
                "call_date",
                "call_time",
            ]
        )
        
        for log in call_logs:
            # Check if record already exists in calling history
            existing_record = frappe.get_all(
                "Calling History",
                filters={
                    "call_id": log.call_id,
                }
            )
            
            if not existing_record:
                # Create new calling history record
                lead_doc = frappe.get_doc("Lead", lead.name)
                lead_doc.append("calling_history", {
                    "call_id": log.call_id,
                    "agent_name": log.agent_name,
                    "call_type": log.call_type,
                    "status": log.status,
                    "call_date": log.call_date,
                    "call_time": log.call_time,
                })
                lead_doc.save()
                frappe.db.commit()

