import mcp.types as types
from mcp.server import Server
import json
import os
from .database import SessionLocal, Complaint, Customer, Employee, Project, Interaction, AgentMemory
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
            name="request_client_info",
            description="Developer Copilot tool: Leave a question on the ticket for the customer agent to ask the client. Use this when the developer needs more info.",
            inputSchema={
                "type": "object",
                "properties": {
                    "complaint_id": {"type": "integer"},
                    "developer_question": {"type": "string", "description": "The exact question to ask the customer"}
                },
                "required": ["complaint_id", "developer_question"]
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
            name="update_ticket_status",
            description="Developer Copilot tool: Update the status of a ticket (e.g., 'IN PROGRESS', 'RESOLVED') and leave a message for the customer.",
            inputSchema={
                "type": "object",
                "properties": {
                    "complaint_id": {"type": "integer"},
                    "new_status": {"type": "string", "description": "Update the status to 'IN PROGRESS', 'RESOLVED', etc."},
                    "developer_message": {"type": "string", "description": "Message explaining the status change to the customer"}
                },
                "required": ["complaint_id", "new_status", "developer_message"]
            }
        ),
        types.Tool(
            name="update_ticket_eta",
            description="Developer Copilot tool: Update the ETA of a ticket and leave a message for the customer timeline.",
            inputSchema={
                "type": "object",
                "properties": {
                    "complaint_id": {"type": "integer"},
                    "new_eta": {"type": "string", "description": "The new estimated time to resolution (e.g. '2 days')"},
                    "developer_message": {"type": "string", "description": "Message explaining the ETA delay or change to the customer"}
                },
                "required": ["complaint_id", "new_eta", "developer_message"]
            }
        ),
        types.Tool(
            name="save_memory",
            description="Agent tool: Save a persistent memory (e.g. successful troubleshooting steps, developer preferences).",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_type": {"type": "string", "description": "'customer', 'supervisor', or 'copilot'"},
                    "memory_key": {"type": "string", "description": "A short, unique identifier for the memory topic"},
                    "memory_value": {"type": "string", "description": "The detailed information to remember"}
                },
                "required": ["agent_type", "memory_key", "memory_value"]
            }
        ),
        types.Tool(
            name="recall_memory",
            description="Agent tool: Retrieve all saved memories for your agent type to help with decision making.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_type": {"type": "string", "description": "'customer', 'supervisor', or 'copilot'"}
                },
                "required": ["agent_type"]
            }
        ),
        types.Tool(
            name="get_dashboard_stats",
            description="Developer Copilot tool: Fetch statistics about the developer dashboard including pending tickets, ticket priorities, and idle developers.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
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
            
            text = f"Status: {comp.status}\nAssigned To: {emp_name}\nPriority: {comp.priority}\nETA: {comp.eta}\nTasks Assigned: {comp.suggested_action}"
            if comp.developer_question:
                text += f"\n\nDEVELOPER REQUEST: The developer has asked for the following information: '{comp.developer_question}'. Please ask the client for this information."
            return [types.TextContent(type="text", text=text)]
            
        elif name == "route_complaint":
            comp_id = arguments.get("complaint_id")
            complaint = db.query(Complaint).filter(Complaint.id == comp_id).first()
            if not complaint:
                return [types.TextContent(type="text", text="Complaint not found.")]
            
            specialty = arguments.get("specialty_required", "")
            engineer = db.query(Employee).filter(Employee.specialty.ilike(f"%{specialty}%"), Employee.is_available == True).first()
            if not engineer:
                # Fallback to any available engineer
                engineer = db.query(Employee).filter(Employee.is_available == True).first()
            
            complaint.priority = arguments.get("priority")
            complaint.eta = arguments.get("eta")
            complaint.predicted_category = arguments.get("category")
            complaint.suggested_action = arguments.get("suggested_action")
            
            if engineer:
                complaint.employee_id = engineer.id
                complaint.status = "ASSIGNED"
                
                # Log Assignment in Timeline
                msg = f"System: Ticket has been formally escalated and assigned to {engineer.name} ({specialty}). Priority: {complaint.priority}, ETA: {complaint.eta}."
                interaction = Interaction(customer_id=complaint.customer_id, complaint_id=complaint.id, role="assistant", content=msg, timestamp=datetime.utcnow())
                db.add(interaction)
                
                db.commit()
                return [types.TextContent(type="text", text=f"Successfully routed to {engineer.name} ({specialty}).")]
            else:
                complaint.status = "NEW"
                
                # Log Unassigned Escalation
                msg = f"System: Ticket has been formally escalated. Waiting for an available engineer specializing in {specialty}. Priority: {complaint.priority}, ETA: {complaint.eta}."
                interaction = Interaction(customer_id=complaint.customer_id, complaint_id=complaint.id, role="assistant", content=msg, timestamp=datetime.utcnow())
                db.add(interaction)
                
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
            
        elif name == "update_ticket_status":
            comp_id = arguments.get("complaint_id")
            comp = db.query(Complaint).filter(Complaint.id == comp_id).first()
            if not comp: return [types.TextContent(type="text", text="Complaint not found.")]
            
            comp.status = arguments.get("new_status")
            msg = f"Developer Status Update: {arguments.get('developer_message')}"
            interaction = Interaction(customer_id=comp.customer_id, complaint_id=comp.id, role="assistant", content=msg, timestamp=datetime.utcnow())
            db.add(interaction)
            db.commit()
            return [types.TextContent(type="text", text=f"Ticket {comp.id} successfully updated. Status is now {comp.status}.")]
            
        elif name == "update_ticket_eta":
            comp_id = arguments.get("complaint_id")
            comp = db.query(Complaint).filter(Complaint.id == comp_id).first()
            if not comp: return [types.TextContent(type="text", text="Complaint not found.")]
            
            comp.eta = arguments.get("new_eta")
            msg = f"Developer ETA Update: {arguments.get('developer_message')}"
            interaction = Interaction(customer_id=comp.customer_id, complaint_id=comp.id, role="assistant", content=msg, timestamp=datetime.utcnow())
            db.add(interaction)
            db.commit()
            return [types.TextContent(type="text", text=f"Ticket {comp.id} successfully updated. ETA is now {comp.eta}.")]

        elif name == "request_client_info":
            comp_id = arguments.get("complaint_id")
            comp = db.query(Complaint).filter(Complaint.id == comp_id).first()
            if not comp: return [types.TextContent(type="text", text="Complaint not found.")]
            
            comp.developer_question = arguments.get("developer_question")
            
            msg = f"Developer Notice: Waiting on customer to provide information regarding: {comp.developer_question}"
            interaction = Interaction(customer_id=comp.customer_id, complaint_id=comp.id, role="assistant", content=msg, timestamp=datetime.utcnow())
            db.add(interaction)
            db.commit()
            
            return [types.TextContent(type="text", text=f"Successfully attached the following question to the ticket for the client: '{comp.developer_question}'")]
            
        elif name == "save_memory":
            mem = AgentMemory(
                agent_type=arguments.get("agent_type"),
                memory_key=arguments.get("memory_key"),
                memory_value=arguments.get("memory_value")
            )
            db.add(mem)
            db.commit()
            return [types.TextContent(type="text", text=f"Successfully saved to {mem.agent_type} memory bank under key '{mem.memory_key}'.")]
            
        elif name == "recall_memory":
            mems = db.query(AgentMemory).filter(AgentMemory.agent_type == arguments.get("agent_type")).all()
            if not mems:
                return [types.TextContent(type="text", text="No memories found.")]
            text = "\n".join([f"Key [{m.memory_key}]: {m.memory_value}" for m in mems])
            return [types.TextContent(type="text", text=text)]
            
        elif name == "get_dashboard_stats":
            unassigned = db.query(Complaint).filter(Complaint.employee_id == None).all()
            pending = db.query(Complaint).filter(Complaint.status.in_(["NEW", "ASSIGNED"])).all()
            idle_devs = db.query(Employee).filter(Employee.is_available == True).all()
            
            stats = []
            stats.append(f"Total Pending/Active Tickets: {len(pending)}")
            stats.append(f"Unassigned Tickets: {len(unassigned)}")
            
            stats.append("\nIdle Developers:")
            for dev in idle_devs:
                stats.append(f"- {dev.name} ({dev.specialty})")
                
            stats.append("\nPending Tickets Summary:")
            for t in pending:
                assigned_to = t.assigned_employee.name if t.assigned_employee else "Unassigned"
                stats.append(f"- #{t.id} [{t.priority}]: {t.text_content[:50]}... (Assigned to: {assigned_to})")
                
            return [types.TextContent(type="text", text="\n".join(stats))]
            
        else:
            raise ValueError(f"Unknown tool: {name}")
    finally:
        db.close()
