from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import base64
import os

from .database import SessionLocal, init_db, Complaint, Customer, Employee, Project, Interaction
from .agent import process_complaint_with_agent

app = FastAPI(title="AMD CX Routing Engine")

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

@app.on_event("startup")
def on_startup():
    init_db()

@app.post("/api/complaints")
async def create_complaint(
    text: str = Form(...),
    customer_id: int = Form(...),
    project_id: int = Form(...),
    image: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    image_b64 = None
    if image:
        contents = await image.read()
        image_b64 = base64.b64encode(contents).decode('utf-8')
    
    project = db.query(Project).filter(Project.id == project_id).first()
    project_name = project.name if project else "Unknown"
    
    complaint = Complaint(
        customer_id=customer_id,
        project_id=project_id,
        text_content=text,
        image_path="uploaded_image" if image_b64 else None
    )
    db.add(complaint)
    db.commit()
    db.refresh(complaint)
    
    # Save initial user interaction
    interaction_user = Interaction(customer_id=customer_id, complaint_id=complaint.id, role="user", content=text)
    db.add(interaction_user)
    db.commit()
    
    agent_result = await process_complaint_with_agent(
        complaint_id=complaint.id,
        text=text,
        image_url=image_b64,
        customer_id=customer_id,
        project_name=project_name,
        chat_history=[]
    )
    
    # Save agent interaction
    if agent_result and agent_result.get("agent_reply"):
        interaction_agent = Interaction(customer_id=customer_id, complaint_id=complaint.id, role="assistant", content=agent_result["agent_reply"])
        db.add(interaction_agent)
        db.commit()
    
    return {"complaint_id": complaint.id, "agent_result": agent_result}

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
    
    # Fetch history
    history = db.query(Interaction).filter(Interaction.complaint_id == complaint_id).order_by(Interaction.timestamp.asc()).all()
    chat_history = [{"role": i.role, "content": i.content} for i in history]
    
    # Add user message
    user_msg = Interaction(customer_id=complaint.customer_id, complaint_id=complaint.id, role="user", content=text)
    db.add(user_msg)
    db.commit()
    
    agent_result = await process_complaint_with_agent(
        complaint_id=complaint.id,
        text=text,
        image_url=None,
        customer_id=complaint.customer_id,
        project_name=project_name,
        chat_history=chat_history
    )
    
    if agent_result and agent_result.get("agent_reply"):
        agent_msg = Interaction(customer_id=complaint.customer_id, complaint_id=complaint.id, role="assistant", content=agent_result["agent_reply"])
        db.add(agent_msg)
        db.commit()
        
    return {"status": "success", "agent_reply": agent_result.get("agent_reply")}

@app.get("/api/dashboard/complaints")
def get_complaints(db: Session = Depends(get_db)):
    complaints = db.query(Complaint).order_by(Complaint.created_at.desc()).all()
    results = []
    for c in complaints:
        emp_name = c.assigned_employee.name if c.assigned_employee else None
        proj_name = c.project.name if c.project else "Unknown"
        results.append({
            "id": c.id,
            "project_name": proj_name,
            "text": c.text_content,
            "priority": c.priority,
            "category": c.predicted_category,
            "assigned_employee": emp_name,
            "status": c.status,
            "suggested_action": c.suggested_action,
            "created_at": c.created_at
        })
    return results

@app.get("/api/tickets/{ticket_id}/timeline")
def get_timeline(ticket_id: int, db: Session = Depends(get_db)):
    history = db.query(Interaction).filter(Interaction.complaint_id == ticket_id).order_by(Interaction.timestamp.asc()).all()
    return [{"role": i.role, "content": i.content, "timestamp": i.timestamp} for i in history]

@app.get("/api/customers")
def get_customers(db: Session = Depends(get_db)):
    customers = db.query(Customer).all()
    return [{"id": c.id, "name": c.name, "tier": c.tier} for c in customers]

@app.get("/api/projects")
def get_projects(db: Session = Depends(get_db)):
    projects = db.query(Project).all()
    return [{"id": p.id, "name": p.name} for p in projects]

@app.get("/api/employees")
def get_employees(db: Session = Depends(get_db)):
    employees = db.query(Employee).all()
    return [{"id": e.id, "name": e.name, "specialty": e.specialty} for e in employees]

app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
