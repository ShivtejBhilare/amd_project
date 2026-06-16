import mcp.types as types
from mcp.server import Server
import json
import os
from .database import SessionLocal, Complaint, Customer, Employee, Project, Interaction
from datetime import datetime

app = Server("cx-routing-mcp")

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="check_ticket_status",
            description="Fetch the status, priority, and ETA for a given complaint ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "complaint_id": {"type": "integer"}
                },
                "required": ["complaint_id"]
            }
        ),
        types.Tool(
            name="route_complaint",
            description="Supervisor tool: Route a complaint to an available engineer based on specialty, set priority and ETA.",
            inputSchema={
                "type": "object",
                "properties": {
                    "complaint_id": {"type": "integer"},
                    "specialty_required": {"type": "string"},
                    "priority": {"type": "string"},
                    "eta": {"type": "string"},
                    "category": {"type": "string"},
                    "suggested_action": {"type": "string"}
                },
                "required": ["complaint_id", "specialty_required", "priority", "eta", "category", "suggested_action"]
            }
        ),
        types.Tool(
            name="search_knowledge_base",
            description="Search the dummy software SRS files to find troubleshooting steps.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_name": {"type": "string"}
                },
                "required": ["project_name"]
            }
        ),
        types.Tool(
            name="search_developer_docs",
            description="Mock web search / documentation search for developers.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"}
                },
                "required": ["query"]
            }
        ),
        types.Tool(
            name="update_ticket",
            description="Developer Copilot tool: Update the ETA of a ticket and leave a message for the customer timeline.",
            inputSchema={
                "type": "object",
                "properties": {
                    "complaint_id": {"type": "integer"},
                    "new_eta": {"type": "string", "description": "The new estimated time to resolution (e.g. '2 days')"},
                    "developer_message": {"type": "string", "description": "Message explaining the delay to the customer"}
                },
                "required": ["complaint_id", "new_eta", "developer_message"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    db = SessionLocal()
    try:
        if name == "check_ticket_status":
            comp = db.query(Complaint).filter(Complaint.id == arguments.get("complaint_id")).first()
            if not comp: return [types.TextContent(type="text", text="Complaint not found.")]
            emp_name = comp.assigned_employee.name if comp.assigned_employee else "Unassigned"
            text = f"Status: {comp.status}, Assigned To: {emp_name}, Priority: {comp.priority}, ETA: {comp.eta}"
            return [types.TextContent(type="text", text=text)]
            
        elif name == "route_complaint":
            comp_id = arguments.get("complaint_id")
            complaint = db.query(Complaint).filter(Complaint.id == comp_id).first()
            if not complaint:
                return [types.TextContent(type="text", text="Complaint not found.")]
            
            specialty = arguments.get("specialty_required")
            engineer = db.query(Employee).filter(Employee.specialty == specialty, Employee.is_available == True).first()
            
            complaint.priority = arguments.get("priority")
            complaint.eta = arguments.get("eta")
            complaint.predicted_category = arguments.get("category")
            complaint.suggested_action = arguments.get("suggested_action")
            
            if engineer:
                complaint.employee_id = engineer.id
                complaint.status = "ASSIGNED"
                db.commit()
                return [types.TextContent(type="text", text=f"Successfully routed to {engineer.name} ({specialty}).")]
            else:
                complaint.status = "NEW"
                db.commit()
                return [types.TextContent(type="text", text=f"No available engineer found for {specialty}. Kept as NEW but prioritized.")]
                
        elif name == "search_knowledge_base":
            project_name = arguments.get("project_name", "").lower()
            srs_dir = os.path.join(os.path.dirname(__file__), "srs_docs")
            
            target_file = None
            if "banking" in project_name: target_file = "banking_app.md"
            elif "commerce" in project_name: target_file = "ecommerce_platform.md"
            elif "health" in project_name: target_file = "healthcare_portal.md"
            
            if target_file and os.path.exists(os.path.join(srs_dir, target_file)):
                with open(os.path.join(srs_dir, target_file), "r") as f:
                    return [types.TextContent(type="text", text=f.read())]
            return [types.TextContent(type="text", text="No specific SRS found for this project.")]
            
        elif name == "search_developer_docs":
            q = arguments.get("query", "").lower()
            if "2fa" in q or "twilio" in q:
                res = "StackOverflow: Make sure the Twilio phone number is verified in the console and environment variables match."
            elif "css" in q or "checkout" in q or "align" in q:
                res = "TailwindCSS: Ensure flex-col and justify-center are properly nested. Check for z-index overrides."
            elif "timeout" in q or "payment" in q or "gateway" in q:
                res = "Stripe Docs: Increase the timeout limit in your webhook handler to 30s. Respond with 200 immediately."
            elif "upload" in q or "pdf" in q or "s3" in q:
                res = "AWS S3: Check CORS configuration on the bucket. Allow PUT method and headers."
            else:
                res = "GitHub Issues: No known open issues for this. Check server logs."
            return [types.TextContent(type="text", text=res)]
            
        elif name == "update_ticket":
            comp_id = arguments.get("complaint_id")
            comp = db.query(Complaint).filter(Complaint.id == comp_id).first()
            if not comp: return [types.TextContent(type="text", text="Complaint not found.")]
            
            comp.eta = arguments.get("new_eta")
            
            msg = f"Developer Update: {arguments.get('developer_message')}"
            interaction = Interaction(customer_id=comp.customer_id, complaint_id=comp.id, role="assistant", content=msg, timestamp=datetime.utcnow())
            db.add(interaction)
            db.commit()
            
            return [types.TextContent(type="text", text=f"Ticket {comp.id} successfully updated. ETA is now {comp.eta}. Message added to timeline.")]
            
        else:
            raise ValueError(f"Unknown tool: {name}")
    finally:
        db.close()
