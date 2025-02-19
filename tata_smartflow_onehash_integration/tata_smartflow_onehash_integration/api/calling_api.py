import frappe
import http.client
import json
from frappe import _
from frappe.utils import now

@frappe.whitelist()
def webhook_call_handler():
    """Handle incoming webhook data for call records"""
    try:
        call_data = frappe.request.json
        frappe.log_error(f"Webhook data", call_data)
        
        # Basic validation
        if not call_data.get('call_id'):
            return {
                "success": False,
                "message": "Invalid webhook data: Missing call ID"
            }
            
        agent_number = format_agent_number(call_data.get('answered_agent_number', ''))
        # customer_number = call_data.get("call_to_number", '').replace('+', '') if call_data.get("call_to_number") else ''

        # Modified customer number logic based on call direction
        if call_data.get('direction') == 'clicktocall':
            # For outbound calls, call_to_number contains the customer number
            customer_number = call_data.get("call_to_number", '').replace('+', '') if call_data.get("call_to_number") else ''
            # Ensure number starts with 91, but avoid adding it twice
            if customer_number and not customer_number.startswith('91'):
                customer_number = '91' + customer_number
        else:
            # For inbound calls, caller_id_number contains the customer number
            customer_number = call_data.get("caller_id_number", '').replace('+', '') if call_data.get("caller_id_number") else ''
            # Ensure number starts with 91, but avoid adding it twice
            if customer_number and not customer_number.startswith('91'):
                customer_number = '91' + customer_number

        # frappe.log_error("Webhook data: customer number", customer_number)
        
        # Create the call log entry
        call_doc = frappe.get_doc({
            "doctype": "Tata Tele Call Logs",
            "uuid": call_data.get('uuid'),
            "call_id": call_data.get('call_id'),
            "agent_name": call_data.get('answered_agent_name'),
            "call_type": "Outbound" if call_data.get('direction') == 'clicktocall' else "Inbound",
            "call_date": call_data.get('start_stamp', '').split(' ')[0] if call_data.get('start_stamp') else now(),
            "call_time": call_data.get('start_stamp', '').split(' ')[1] if call_data.get('start_stamp') else now(),
            "last_entry_time": call_data.get('end_stamp'),
            "duration": call_data.get('duration'),
            "recording_url": call_data.get('recording_url'),
            "agent_phone_number": agent_number,
            "customer_number": customer_number,
            "status": get_call_status(call_data),
        })

        # Check for existing call log
        # existing_log = frappe.get_all(
        #     "Tata Tele Call Logs",
        #     filters={"call_id": call_data.get('call_id')},
        #     limit=1
        # )
        existing_log = frappe.db.exists("Tata Tele Call Logs", {"call_id": call_data.get('call_id')})

        if existing_log:
            frappe.log_error(f"Call log already exists for call_id: {call_data.get('call_id')}")
        else:
            call_doc.insert(ignore_permissions=True)
            
            # Create lead for missed inbound calls
            if call_doc.call_type == "Inbound":
                create_lead_for_missed_call(customer_number, call_data)

            # Handle missed agents if present
            if call_data.get('missed_agent') and isinstance(call_data['missed_agent'], list):
                missed_agents = []
                for agent in call_data['missed_agent']:
                    missed_agents.append({
                        "agent_name": agent.get('name'),
                        "number": format_agent_number(agent.get('number'))
                    })
                insert_missed_agents(call_doc.name, missed_agents)

            # Handle hangup records
            if call_data.get('call_flow'):
                insert_hangup_records(call_doc.name, call_data['call_flow'])

            frappe.db.commit()
        
        sync_to_lead_history(call_doc)

        return {
            "success": True,
            "message": "Webhook data processed successfully"
        }

    except Exception as e:
        frappe.log_error(f"Webhook Processing Error: {str(e)}", "Tata Tele Webhook Error")
        return {
            "success": False,
            "message": f"Error processing webhook: {str(e)}"
        }
    
    
def sync_to_lead_history(call_doc):
    """Sync a single call record to corresponding Lead's calling history"""
    try:
        # Find leads with matching mobile number
        frappe.log_error(f"call_doc details: {call_doc.name}, type: {type(call_doc)}", "Call Doc Input")

        leads = frappe.db.get_list(
            "Lead",
            filters={"mobile_no": call_doc.customer_number},
            fields=["name"]
        )

        for lead in leads:
            lead_doc = frappe.get_doc("Lead", lead.name)

            # Update lead's call status with latest status
            lead_doc.call_status = call_doc.call_status
            
            # Check if call record already exists in calling history
            existing_record = False
            for history_entry in lead_doc.calling_history:
                if history_entry.call_id == call_doc.call_id:
                    # Update existing record
                    history_entry.update({
                        "agent_name": call_doc.agent_name,
                        "call_type": call_doc.call_type,
                        "status": call_doc.status,
                        "call_date": call_doc.call_date,
                        "call_time": call_doc.call_time,
                        "duration": call_doc.duration,
                    })
                    existing_record = True
                    break
            
            # If record doesn't exist, add new entry
            if not existing_record:
                lead_doc.append("calling_history", {
                    "call_id": call_doc.call_id,
                    "agent_name": call_doc.agent_name,
                    "call_type": call_doc.call_type,
                    "status": call_doc.status,
                    "call_date": call_doc.call_date,
                    "call_time": call_doc.call_time,
                    "duration": call_doc.duration,
                })
            
            lead_doc.save(ignore_permissions=True)
            frappe.log_error(f"Transaction committed for lead {lead.name}")
            
    except Exception as e:
        frappe.log_error(f"Error syncing call record to lead history: {str(e)}")

def get_call_status(call_data):
    """Determine call status based on webhook data"""
    if call_data.get('call_status'):
        return call_data['call_status'].capitalize()
    

    if call_data.get('call_connected') == '1':
        return 'Answered'
    elif call_data.get('call_connected') == '0':
        return 'Missed'
    
    if call_data.get('hangup_cause') == 'NO_ANSWER':
        return 'Missed'
    elif call_data.get('billsec', 0) > 0:
        return 'Answered'
    else:
        return 'Failed'
    
def create_lead_for_missed_call(phone_number, call_data=None):
    """Create a new lead for missed calls if it doesn't exist"""
    try:
        frappe.log_error("Starting lead creation for phone", phone_number)
        
        # Add validation logging
        exists_check = frappe.db.exists("Lead", {"mobile_no": phone_number})
        
        if phone_number and not exists_check:
            if call_data:
                call_status = get_call_status(call_data)
            else:
                call_status = "" 
            
            frappe.log_error("call status is", call_status)

            new_lead = frappe.get_doc({
                "doctype": "Lead",
                "first_name": "Student",
                "source": "IVR Lead",
                "mobile_no": phone_number,
                "call_status": call_status,
            })
            # frappe.log_error("Lead doc created", new_lead.as_dict())
            
            # Add explicit commit
            new_lead.insert(ignore_permissions=True)
            frappe.db.commit()
            
            # frappe.log_error("Lead saved successfully", new_lead.name)
        else:
            frappe.log_error("Skipping lead creation - either no phone or lead exists", 
                           f"Phone: {phone_number}, Exists: {exists_check}")
    except Exception as e:
        frappe.log_error(f"Error creating lead for missed call: {str(e)}\n{frappe.get_traceback()}")


def format_agent_number(phone_number):
    """Format agent phone number by removing +91 prefix"""
    if not phone_number:
        return phone_number
    
    phone_number = phone_number.strip()
    
    if phone_number.startswith('+91'):
        phone_number = phone_number[3:]   
        
    return phone_number

def insert_missed_agents(call_log_name, missed_agents):
    """Update missed agents for a call log"""
    try:
        call_doc = frappe.get_doc("Tata Tele Call Logs", call_log_name)
        call_doc.missed_agents = []
        
        for agent in missed_agents:
            call_doc.append("missed_agents", {
                "agent_name": agent["agent_name"],
                "number": format_agent_number(agent.get("agent_number") or agent.get("number"))
            })
        
        call_doc.save()
    except Exception as e:
        frappe.log_error(f"Error updating missed agents: {str(e)}")

def insert_hangup_records(call_log_name, call_flow):
    """Update hangup records for a call log"""
    try:
        call_doc = frappe.get_doc("Tata Tele Call Logs", call_log_name)
        call_doc.hang_up_call_records = []
        
        for flow in call_flow:
            call_doc.append("hang_up_call_records", {
                "id": flow.get("id"),
                "agent_name": flow.get("name"),
                "disposition": flow.get("dialst"),
                "hangup_time": flow.get('time')
            })
        
        call_doc.save()
    except Exception as e:
        frappe.log_error(f"Error updating hangup records: {str(e)}")
        
        
######################################################################################################

#CAN BE USED IF TATA TELE FETCH CALL RECORDS API IS USED


# @frappe.whitelist(allow_guest=True)
# def fetch_call_records():
#     try:    
#         # Get settings from Custom DocType
#         settings = frappe.get_single("Tata Tele API Cloud Settings")
#         if not settings:
#             return {
#                 "success": False,
#                 "message": "Tata Tele API Cloud Settings not configured correctly"
#             }
            
#         # Get decrypted auth token
#         auth_token = frappe.utils.password.get_decrypted_password(
#             "Tata Tele API Cloud Settings",
#             "Tata Tele API Cloud Settings",
#             "api_token"
#         )
        
#         # Prepare API call
#         base_url = settings.url
#         endpoint = "/v1/call/records"
        
#         headers = {
#             "accept": "application/json",
#             "content-type": "application/json",
#             "Authorization": auth_token
#         }
        
#         conn = http.client.HTTPSConnection(base_url)
#         conn.request(
#             "GET",
#             endpoint,
#             headers=headers
#         )
        
#         # Make API call using http.client
#         conn = http.client.HTTPSConnection(base_url)
#         conn.request("GET", endpoint, headers=headers)
#         response = conn.getresponse()
#         response_data = json.loads(response.read().decode("utf-8"))
        
#         if response.status == 200 and "results" in response_data:
#             for call in response_data["results"]:
#                 # Create or update call log
#                 call_log = create_call_log(call)
                
#                 # Update missed agents if present
#                 if call.get("missed_agents"):
#                     insert_missed_agents(call_log.name, call["missed_agents"])
                    
#                 # Update hangup records if present
#                 if call.get("agent_hangup_data"):
#                     insert_hangup_records(call_log.name, call["agent_hangup_data"])
                
#             return {
#                 "success": True,
#                 "message": "Call records processed successfully"
#             }
#         else:
#             return {
#                 "success": False,
#                 "message": f"Failed to fetch tata tele call records: {response_data.get('message', 'Unknown error')}"
#             }
            
#     except Exception as e:
#         return {
#             "success": False,
#             "message": f"Error: {str(e)}"
#         }
#     finally:
#         if 'conn' in locals():
#             conn.close()
            
# def format_phone_number(phone_number):
#     """Remove plus sign from phone number if present, keeping country code"""
#     if phone_number.startswith("+"):
#         return phone_number[1:]
#     return phone_number

# def format_agent_number(phone_number):
#     if not phone_number:
#         return phone_number
    
#     phone_number = phone_number.strip()
    
#     if phone_number.startswith('+91'):
#         phone_number = phone_number[3:]   
        
#     return phone_number
        
             
# # Helping functions for fetch_call_records method       
# def create_call_log(call_data):
#     """Create or update call log entry"""
#     existing_log = frappe.get_all(
#         "Tata Tele Call Logs",
#         filters={"call_id": call_data["call_id"]},
#         limit=1
#     )
    
#     formatted_number = format_phone_number(call_data["client_number"])
#     formatted_agent_number = format_agent_number(call_data["agent_number"])
    
#     call_doc = frappe.get_doc({
#         "doctype": "Tata Tele Call Logs",
#         "call_id": call_data["call_id"],
#         "agent_name": call_data["agent_name"],
#         "call_type": "Inbound" if call_data["direction"] == "inbound" else "Outbound",
#         "call_date": call_data["date"],
#         "call_time": call_data["time"],
#         "last_entry_time": call_data["end_stamp"],
#         "duration": call_data["call_duration"],
#         "customer_number": formatted_number,
#         "status": call_data["status"].capitalize(),
#         "recording_url": call_data.get("recording_url"),
#         "description": call_data["description"],
#         "agent_phone_number": formatted_agent_number
#     })
    
#     if existing_log:
#         frappe.log_error("call log already exists")
#     else:
#         call_doc.insert(ignore_permissions=True)
        
#     if call_doc.call_type == "Inbound" and call_doc.status == "Missed":
#         try:
            
#             existing_lead = frappe.db.exists("Lead", {"mobile_no": formatted_number})

#             if not existing_lead:
#                 new_lead = frappe.new_doc("Lead")

#                 # Set required fields 
#                 new_lead.first_name = "Student"
#                 new_lead.source = "Missed Calls"
#                 new_lead.mobile_no = formatted_number

#                 # Insert the new lead
#                 new_lead.save(ignore_permissions=True)

#         except Exception as e:
#             frappe.log_error(f"Error creating lead for missed call {call_doc.call_id}: {str(e)}")
        
#     return call_doc

# def insert_missed_agents(call_log_name, missed_agents):
#     """Update missed agents for a call log"""
#     call_doc = frappe.get_doc("Tata Tele Call Logs", call_log_name)
#     call_doc.missed_agents = []
    
#     for agent in missed_agents:
#         call_doc.append("missed_agents", {
#             "agent_name": agent["name"],
#             "number": agent["number"]
#         })
    
#     call_doc.save()

# def insert_hangup_records(call_log_name, hangup_data):
#     """Update hangup records for a call log"""
#     call_doc = frappe.get_doc("Tata Tele Call Logs", call_log_name)
#     call_doc.hang_up_call_records = []
    
#     for record in hangup_data:
#         call_doc.append("hang_up_call_records", {
#             "id": record["id"],
#             "agent_name": record["name"],
#             "agent_id": record["id"],
#             "disposition": record["disposition"],
#         })
    
#     call_doc.save()
    
#####################################################################################################################


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
        
        auth_token = frappe.utils.password.get_decrypted_password(
            "Tata Tele API Cloud Settings",
            "Tata Tele API Cloud Settings",
            "api_token"
        )
        
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
        
        if response_data.get("success") == True:
            lead_doc = frappe.get_doc("Lead", docname)
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
        frappe.log_error("inbound call data", data)
        
        # Get settings
        settings = frappe.get_single("Tata Tele API Cloud Settings")
        if not settings:
            frappe.throw(_("Tata Tele API Cloud Settings not configured"))

        caller_number = data.get("caller_id_number", "")
        if not caller_number:
            return {"success": False, "message": "No caller ID provided"}

        # Get answer_agent_number from the incoming data
        answer_agent_number = data.get("answer_agent_number", "")
        if not answer_agent_number:
            return {"success": False, "message": "No agent number provided"}

        # Strip the +91 prefix if present to match the format in database
        clean_agent_number = answer_agent_number
        if clean_agent_number.startswith("+91"):
            clean_agent_number = clean_agent_number[3:]  # Remove "+91"
        
        # Find the corresponding user in Tata Tele Users doctype
        tata_tele_users = frappe.get_list("Tata Tele Users", 
            filters={"phone_number": clean_agent_number},
            fields=["user"]
        )
        
        if not tata_tele_users:
            frappe.log_error("Agent notification error", f"No matching Tata Tele User found for agent number {answer_agent_number}")
            return {"success": False, "message": "No matching Tata Tele User found"}
        
        target_user = tata_tele_users[0].user
        
        clean_number = caller_number.strip()
        if clean_number.startswith("+"):
            clean_number = clean_number[1:]  
        
        last_ten_digits = clean_number[-10:] if len(clean_number) >= 10 else clean_number
        
        formatted_number = f"91{last_ten_digits}" if len(last_ten_digits) == 10 else clean_number
        
        frappe.log_error("Searching for number", formatted_number)
        
        # leads = frappe.get_list("Lead", 
        #     filters=[
        #         ["mobile_no", "=", caller_number] | 
        #         ["mobile_no", "=", clean_number] | 
        #         ["mobile_no", "=", last_ten_digits] | 
        #         ["mobile_no", "like", f"%{last_ten_digits}"]
        #     ],
        #     fields=["name", "first_name", "mobile_no"]
        # )

        leads = frappe.get_list("Lead", 
            filters=[
                ["mobile_no", "like", formatted_number]
            ],
            fields=["name", "first_name", "mobile_no"]
        )
        
        frappe.log_error("Matching leads", leads)
        
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
            
            # Send the notification only to the specific user
            frappe.publish_realtime(
                event='inbound_call_notification',
                message=notification_data,
                user=target_user
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
# def handle_inbound_call():
#     try:
#         if not frappe.request or not frappe.request.data:
#             frappe.throw(_("No data received"))
            
#         data = json.loads(frappe.request.data)
#         frappe.log_error("inbound call data", data)
        
#         # Get settings
#         settings = frappe.get_single("Tata Tele API Cloud Settings")
#         if not settings:
#             frappe.throw(_("Tata Tele API Cloud Settings not configured"))

#         caller_number = data.get("caller_id_number", "")
#         if not caller_number:
#             return {"success": False, "message": "No caller ID provided"}

#         clean_number = caller_number.strip()
#         if clean_number.startswith("+"):
#             clean_number = clean_number[1:]  
        
#         last_ten_digits = clean_number[-10:] if len(clean_number) >= 10 else clean_number
        
#         frappe.log_error("Searching for number patterns", 
#                          f"Original: {caller_number}, Last 10 digits: {last_ten_digits}")
        
#         # Find matching lead using get_list
#         # leads = frappe.get_list("Lead", 
#         #     filters={"mobile_no": data.get("caller_id_number")},
#         #     fields=["name", "first_name", "mobile_no"]
#         # )

#         leads = frappe.get_list("Lead", 
#             filters=[
#                 ["mobile_no", "=", caller_number] | 
#                 ["mobile_no", "=", clean_number] | 
#                 ["mobile_no", "=", last_ten_digits] | 
#                 ["mobile_no", "like", f"%{last_ten_digits}"]
#             ],
#             fields=["name", "first_name", "mobile_no"]
#         )
        
#         frappe.log_error("Matching leads", leads)
        
#         if leads:
#             lead = leads[0]  # Get first matching lead
            
#             # Send notification with lead info
#             notification_data = {
#                 "caller_number": data.get("caller_id_number"),
#                 "lead_number": lead.mobile_no,
#                 "lead_name": lead.first_name,
#                 "lead_id": lead.name 
#             }
            
#             frappe.get_doc("Lead", lead.name).add_comment(
#                 "Info",
#                 f"Incoming call received from {data.get('caller_id_number')}"
#             )
            
#             frappe.publish_realtime(
#                 event='inbound_call_notification',
#                 message=notification_data,
#                 user=frappe.session.user
#             )
            
#             return {
#                 "success": True,
#                 "message": "Lead call notification sent successfully"
#             }
        
#         return {
#             "success": False,
#             "message": "No matching lead found"
#         }
            
#     except Exception as e:
#         frappe.logger().error(f"Inbound lead call error: {str(e)}")
#         return {
#             "success": False,
#             "message": f"Failed to process inbound call: {str(e)}"
#         }

############################################################################################################################

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
        
        
# def sync_call_records():
#     """
#     Sync call records from Tata Tele Call Logs to Lead's calling history
#     """
#     # Get all leads with mobile numbers
#     leads = frappe.get_all(
#         "Lead",
#         filters={"mobile_no": ["!=", ""]},
#         fields=["name", "mobile_no"]
#     )
    
#     for lead in leads:
#         lead_doc = frappe.get_doc("Lead", lead.name)
#         # Search for call records in Tata Tele Call Logs
#         call_logs = frappe.get_all(
#             "Tata Tele Call Logs",
#             filters={
#                 "customer_number": lead.mobile_no
#             },
#             fields=[
#                 "call_id",
#                 "agent_name",
#                 "call_type",
#                 "status",
#                 "call_date",
#                 "call_time",
#                 "duration"
#             ],
#             order_by="call_date DESC, call_time DESC"
#         )
        
#         updated = False
        
#         if call_logs:
#             latest_call = call_logs[0]
#             lead_doc.call_status = latest_call.status
#             updated = True
        
#         for log in call_logs:
#             # Check if record already exists in calling history
#             existing_record = frappe.get_all(
#                 "Calling History",
#                 filters={
#                     "call_id": log.call_id,
#                 }
#             )
            
            
#             if not existing_record:
#                 lead_doc.append("calling_history", {
#                     "call_id": log.call_id,
#                     "agent_name": log.agent_name,
#                     "call_type": log.call_type,
#                     "status": log.status,
#                     "call_date": log.call_date,
#                     "call_time": log.call_time,
#                     "duration": log.duration
#                 })
                
#                 updated = True

#             else:
#                 # If record exists, update existing record
#                 for history_entry in lead_doc.calling_history:
#                     if history_entry.call_id == log.call_id:
#                         history_entry.update({
#                             "agent_name": log.agent_name,
#                             "call_type": log.call_type,
#                             "status": log.status,
#                             "call_date": log.call_date,
#                             "call_time": log.call_time,
#                             "duration": log.duration
#                         })
#                         updated = True
#                         break
                
#         if updated:
#             lead_doc.save()
#             frappe.db.commit()

