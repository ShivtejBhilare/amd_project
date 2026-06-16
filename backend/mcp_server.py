import mcp.types as types
from mcp.server import Server
from pydantic import AnyUrl
import json
import os
from .database import SessionLocal, Complaint, Customer, Employee, Project

app = Server("cx-routing-mcp")

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="fetch_customer_history",
            description="Fetch past complaints and interactions for a given customer ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "customer_id": {"type": "integer", "description": "The ID of the customer"}
                },
                "required": ["customer_id"]
            }
        ),
        types.Tool(
            name="route_complaint",
            description="Route a complaint to an available engineer based on their specialty.",
            inputSchema={
                "type": "object",
                "properties": {
                    "complaint_id": {"type": "integer"},
                    "specialty_required": {"type": "string", "description": "Specialty required (e.g. GPU Drivers, Thermal Management, Hardware Replacements, CPU Performance)"},
                    "priority": {"type": "string", "description": "LOW, MEDIUM, HIGH, CRITICAL"},
                    "category": {"type": "string", "description": "Classification category"},
                    "suggested_action": {"type": "string", "description": "Suggested next best action for the human agent to take"}
                },
                "required": ["complaint_id", "specialty_required", "priority", "category", "suggested_action"]
            }
        ),
        types.Tool(
            name="search_knowledge_base",
            description="Search the dummy SRS files to find troubleshooting steps or context for a specific project.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_name": {"type": "string", "description": "Name of the project (e.g. Ryzen, Radeon, Adrenalin)"}
                },
                "required": ["project_name"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    db = SessionLocal()
    try:
        if name == "fetch_customer_history":
            customer_id = arguments.get("customer_id")
            customer = db.query(Customer).filter(Customer.id == customer_id).first()
            if not customer:
                return [types.TextContent(type="text", text="Customer not found.")]
            
            history = {"tier": customer.tier, "complaints": []}
            for comp in customer.complaints:
                history["complaints"].append({
                    "id": comp.id,
                    "status": comp.status,
                    "category": comp.predicted_category,
                    "created_at": str(comp.created_at)
                })
            return [types.TextContent(type="text", text=json.dumps(history))]
            
        elif name == "route_complaint":
            comp_id = arguments.get("complaint_id")
            complaint = db.query(Complaint).filter(Complaint.id == comp_id).first()
            if not complaint:
                return [types.TextContent(type="text", text="Complaint not found.")]
            
            specialty = arguments.get("specialty_required")
            engineer = db.query(Employee).filter(Employee.specialty == specialty, Employee.is_available == True).first()
            
            complaint.priority = arguments.get("priority")
            complaint.predicted_category = arguments.get("category")
            complaint.suggested_action = arguments.get("suggested_action")
            
            if engineer:
                complaint.employee_id = engineer.id
                complaint.status = "ASSIGNED"
                db.commit()
                return [types.TextContent(type="text", text=f"Successfully routed complaint {comp_id} to engineer {engineer.name} ({specialty}).")]
            else:
                complaint.status = "NEW"
                db.commit()
                return [types.TextContent(type="text", text=f"No available engineer found for {specialty}. Kept as NEW but prioritized.")]
                
        elif name == "search_knowledge_base":
            project_name = arguments.get("project_name", "").lower()
            srs_dir = os.path.join(os.path.dirname(__file__), "srs_docs")
            found_text = "No specific SRS found for this project."
            
            target_file = None
            if "ryzen" in project_name: target_file = "ryzen_9_7950x.md"
            elif "radeon" in project_name or "rx" in project_name: target_file = "radeon_rx_7900.md"
            elif "adrenalin" in project_name or "software" in project_name: target_file = "adrenalin_software.md"
            
            if target_file:
                with open(os.path.join(srs_dir, target_file), "r") as f:
                    found_text = f.read()
            
            return [types.TextContent(type="text", text=found_text)]
            
        else:
            raise ValueError(f"Unknown tool: {name}")
    finally:
        db.close()
