from fastapi import FastAPI, Form, Depends, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import base64
import os

from .database import SessionLocal, init_db, Complaint, Customer, Employee, Project, Interaction
from .agent import customer_agent_flow, supervisor_agent_flow, developer_agent_flow, get_model_status

app = FastAPI(title="AMD Multi-Agent CX Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/api/status")
def api_status():
    return {"model_status": get_model_status()}

@app.on_event("startup")
def on_startup():
    init_db()

@app.post("/api/complaints")
async def create_complaint(
    background_tasks: BackgroundTasks,
    customer_id: int = Form(...),
    project_id: int = Form(...),
    text: str = Form(...),
    db: Session = Depends(get_db)
):
    comp = Complaint(customer_id=customer_id, project_id=project_id, text_content=text, status="NEW")
    db.add(comp)
    db.commit()
    db.refresh(comp)
    
    # Save the initial message to interaction log
    interaction = Interaction(customer_id=customer_id, complaint_id=comp.id, role="user", content=text)
    db.add(interaction)
    db.commit()
    
    project = db.query(Project).filter(Project.id == project_id).first()
    
    # Initial Auto-reply / Info gathering
    agent_result = await customer_agent_flow(comp.id, text, project.name, [])
    
    # Save agent response
    agent_msg = Interaction(customer_id=customer_id, complaint_id=comp.id, role="assistant", content=agent_result["reply"])
    db.add(agent_msg)
    db.commit()
    
    # Background Task: Trigger Supervisor Agent
    async def auto_route_ticket():
        print(f"Background Task Triggered: Supervisor assigning Ticket #{comp.id}")
        transcript = f"Customer: {text}"
        await supervisor_agent_flow(comp.id, transcript, project.name)

    background_tasks.add_task(auto_route_ticket)
    
    return {"complaint_id": comp.id, "status": comp.status, "agent_reply": agent_result["reply"]}

@app.post("/api/chat")
async def send_chat(
    complaint_id: int = Form(...),
    text: str = Form(...),
    db: Session = Depends(get_db)
):
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")
        
    project = db.query(Project).filter(Project.id == complaint.project_id).first()
    project_name = project.name if project else "Unknown"
    
    history = db.query(Interaction).filter(Interaction.complaint_id == complaint_id).order_by(Interaction.timestamp.asc()).all()
    chat_history = [{"role": i.role, "content": i.content} for i in history]
    
    user_msg = Interaction(customer_id=complaint.customer_id, complaint_id=complaint.id, role="user", content=text)
    db.add(user_msg)
    db.commit()
    
    # 1. Customer Agent reads history and acts
    agent_result = await customer_agent_flow(complaint.id, text, project_name, chat_history)
    
    # 2. If escalated, trigger Supervisor Agent in background
    if agent_result["status"] == "escalated":
        history = db.query(Interaction).filter(Interaction.complaint_id == complaint_id).order_by(Interaction.timestamp.asc()).all()
        transcript = "\n".join([f"{i.role}: {i.content}" for i in history])
        await supervisor_agent_flow(complaint.id, transcript, project_name)
    
    agent_msg = Interaction(customer_id=complaint.customer_id, complaint_id=complaint.id, role="assistant", content=agent_result["reply"])
    db.add(agent_msg)
    db.commit()
        
    return {"status": "success", "agent_reply": agent_result["reply"]}

@app.post("/api/developer_chat")
async def dev_chat(
    query: str = Form(...),
    chat_history: str = Form("[]"),
    ticket_id: int = Form(None),
    db: Session = Depends(get_db)
):
    import json
    try:
        parsed_history = json.loads(chat_history)
    except:
        parsed_history = []
        
    history_text = ""
    if ticket_id:
        history = db.query(Interaction).filter(Interaction.complaint_id == ticket_id).order_by(Interaction.timestamp.asc()).all()
        history_text = "\n".join([f"{i.role}: {i.content}" for i in history])
        
    # Developer Copilot Agent Flow
    result = await developer_agent_flow(query, parsed_history, history_text, ticket_id)
    return {"reply": result["reply"]}

@app.get("/api/customer/tickets/{customer_id}")
def get_customer_tickets(customer_id: int, db: Session = Depends(get_db)):
    complaints = db.query(Complaint).filter(Complaint.customer_id == customer_id).order_by(Complaint.created_at.desc()).all()
    results = []
    for c in complaints:
        proj_name = c.project.name if c.project else "Unknown"
        results.append({
            "id": c.id, "project_name": proj_name, "status": c.status, 
            "priority": c.priority, "eta": c.eta, "text": c.text_content
        })
    return results

@app.post("/api/admin/assign_backlog")
async def assign_backlog(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    unassigned = db.query(Complaint).filter(Complaint.employee_id == None).all()
    count = len(unassigned)
    
    async def process_backlog(tickets):
        for comp in tickets:
            project_name = comp.project.name if comp.project else "Unknown"
            
            # Fetch the entire conversation history for this ticket to give the Supervisor full context
            history = db.query(Interaction).filter(Interaction.complaint_id == comp.id).order_by(Interaction.timestamp.asc()).all()
            transcript = "\n".join([f"{i.role}: {i.content}" for i in history])
            if not transcript:
                transcript = f"Customer: {comp.text_content}"
                
            print(f"Sweeping Backlog: Assigning Ticket #{comp.id}")
            await supervisor_agent_flow(comp.id, transcript, project_name)
            
    if count > 0:
        background_tasks.add_task(process_backlog, unassigned)
        
    return {"message": f"Queued {count} unassigned tickets for background routing."}

@app.get("/api/dashboard/complaints")
def get_complaints(db: Session = Depends(get_db)):
    complaints = db.query(Complaint).order_by(Complaint.created_at.desc()).all()
    results = []
    for c in complaints:
        emp_name = c.assigned_employee.name if c.assigned_employee else None
        proj_name = c.project.name if c.project else "Unknown"
        results.append({
            "id": c.id, "project_name": proj_name, "text": c.text_content,
            "priority": c.priority, "assigned_employee": emp_name,
            "status": c.status, "eta": c.eta
        })
    return results

@app.get("/api/tickets/{ticket_id}/timeline")
def get_timeline(ticket_id: int, db: Session = Depends(get_db)):
    history = db.query(Interaction).filter(Interaction.complaint_id == ticket_id).order_by(Interaction.timestamp.asc()).all()
    return [{"role": i.role, "content": i.content, "timestamp": i.timestamp} for i in history]

@app.get("/api/customers")
def get_customers(db: Session = Depends(get_db)):
    return [{"id": c.id, "name": c.name} for c in db.query(Customer).all()]

@app.get("/api/projects")
def get_projects(db: Session = Depends(get_db)):
    return [{"id": p.id, "name": p.name} for p in db.query(Project).all()]

@app.get("/api/employees")
def get_employees(db: Session = Depends(get_db)):
    return [{"id": e.id, "name": e.name, "specialty": e.specialty} for e in db.query(Employee).all()]

app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
