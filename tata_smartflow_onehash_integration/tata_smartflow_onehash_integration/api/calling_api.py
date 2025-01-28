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
            
# Helping functions for fetch_call_records method       
def create_call_log(call_data):
    """Create or update call log entry"""
    existing_log = frappe.get_all(
        "Tata Tele Call Logs",
        filters={"call_id": call_data["call_id"]},
        limit=1
    )
    
    call_doc = frappe.get_doc({
        "doctype": "Tata Tele Call Logs",
        "call_id": call_data["call_id"],
        "agent_name": call_data["agent_name"],
        "call_type": "Inbound" if call_data["direction"] == "inbound" else "Outbound",
        "call_date": call_data["date"],
        "call_time": call_data["time"],
        "last_entry_time": call_data["end_stamp"],
        "duration": call_data["call_duration"],
        "customer_number": call_data["client_number"],
        "status": call_data["status"].capitalize(),
        "recording_url": call_data.get("recording_url"),
        "description": call_data["description"]
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

# @frappe.whitelist()
# def hangup_call(call_id):
#     try:
#         # Get settings
#         settings = frappe.get_single("Smartflo Settings")
#         if not settings:
#             return {
#                 "success": False,
#                 "message": "Smartflo settings not configured"
#             }
            
#         auth_token = frappe.utils.password.get_decrypted_password(
#             "Smartflo Settings",
#             "Smartflo Settings",
#             "auth_token"
#         )
        
#         # Prepare API call
#         base_url = "api-smartflo.tatateleservices.com"
#         endpoint = "/v1/hangup_call"
        
#         headers = {
#             "accept": "application/json",
#             "content-type": "application/json",
#             "Authorization": f"Bearer {auth_token}"
#         }
        
#         payload = {
#             "call_id": call_id
#         }
        
#         # Make API call using http.client
#         conn = http.client.HTTPSConnection(base_url)
#         conn.request(
#             "POST",
#             endpoint,
#             body=json.dumps(payload),
#             headers=headers
#         )
        
#         response = conn.getresponse()
#         response_data = json.loads(response.read().decode("utf-8"))
        
#         if response.status == 200:
#             # Update Call Log
#             call_logs = frappe.get_all(
#                 "Call Log",
#                 filters={
#                     "call_id": call_id,
#                     "status": "In Progress"
#                 },
#                 limit=1
#             )
            
#             if call_logs:
#                 call_log = frappe.get_doc("Call Log", call_logs[0].name)
#                 call_log.status = "Completed"
#                 call_log.end_time = now()
#                 call_log.save(ignore_permissions=True)
            
#             return {
#                 "success": True,
#                 "message": "Call ended successfully"
#             }
#         else:
#             return {
#                 "success": False,
#                 "message": f"Failed to end call: {response_data.get('message', 'Unknown error')}"
#             }
            
#     except Exception as e:
#         frappe.log_error(f"Hangup Call Error: {str(e)}")
#         return {
#             "success": False,
#             "message": f"Error: {str(e)}"
#         }
#     finally:
#         if 'conn' in locals():
#             conn.close()