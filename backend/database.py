import os
from datetime import datetime, timedelta
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_URL = f"sqlite:///{os.path.join(BASE_DIR, 'cx_routing_v3.db')}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class Customer(Base):
    __tablename__ = "customers"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    email = Column(String, unique=True, index=True)
    tier = Column(String, default="Standard")
    
    complaints = relationship("Complaint", back_populates="customer")
    interactions = relationship("Interaction", back_populates="customer")

class Employee(Base):
    __tablename__ = "employees"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    specialty = Column(String) # 'Frontend Developer', 'Backend Developer', 'Database Admin', 'Security Analyst'
    is_available = Column(Boolean, default=True)
    
    assigned_complaints = relationship("Complaint", back_populates="assigned_employee")

class Project(Base):
    __tablename__ = "projects"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    
    complaints = relationship("Complaint", back_populates="project")

class Complaint(Base):
    __tablename__ = "complaints"
    
    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"))
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    
    text_content = Column(Text)
    image_path = Column(String, nullable=True)
    
    predicted_category = Column(String, nullable=True)
    priority = Column(String, default="MEDIUM") # LOW, MEDIUM, HIGH, CRITICAL
    status = Column(String, default="NEW") # NEW, ASSIGNED, RESOLVED
    eta = Column(String, nullable=True) # e.g. '2-4 hours'
    
    suggested_action = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    customer = relationship("Customer", back_populates="complaints")
    project = relationship("Project", back_populates="complaints")
    assigned_employee = relationship("Employee", back_populates="assigned_complaints")
    interactions = relationship("Interaction", back_populates="complaint")

class Interaction(Base):
    __tablename__ = "interactions"
    
    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"))
    complaint_id = Column(Integer, ForeignKey("complaints.id"), nullable=True)
    
    role = Column(String)
    content = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    customer = relationship("Customer", back_populates="interactions")
    complaint = relationship("Complaint", back_populates="interactions")

def init_db():
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    
    if not db.query(Customer).first():
        print("Seeding dummy data...")
        c1 = Customer(name="Acme Corp", email="john@acme.com", tier="Enterprise")
        c2 = Customer(name="Startup Inc", email="jane@startup.com", tier="Standard")
        db.add_all([c1, c2])
        
        e1 = Employee(name="Alice Walker", specialty="Frontend Developer", is_available=True)
        e2 = Employee(name="Bob Smith", specialty="Backend Developer", is_available=True)
        e3 = Employee(name="Charlie Spark", specialty="Database Admin", is_available=True)
        e4 = Employee(name="Diana Core", specialty="Security Analyst", is_available=False)
        db.add_all([e1, e2, e3, e4])
        
        p1 = Project(name="Banking App")
        p2 = Project(name="E-commerce Platform")
        p3 = Project(name="Healthcare Portal")
        db.add_all([p1, p2, p3])
        
        db.commit()
        
        # Tickets
        t1 = Complaint(
            customer_id=c1.id, project_id=p1.id, employee_id=e4.id,
            text_content="Users are bypassing 2FA on the login screen.",
            predicted_category="Security Vulnerability", priority="CRITICAL", status="ASSIGNED",
            eta="1 hour",
            suggested_action="Immediate patch required on the auth service.",
            created_at=datetime.utcnow() - timedelta(hours=2)
        )
        t2 = Complaint(
            customer_id=c2.id, project_id=p2.id, employee_id=e1.id,
            text_content="The checkout button is misaligned on mobile.",
            predicted_category="UI Bug", priority="LOW", status="RESOLVED",
            eta="24 hours",
            suggested_action="Customer instructed to clear cache. Developer pushed CSS fix.",
            created_at=datetime.utcnow() - timedelta(days=1)
        )
        t3 = Complaint(
            customer_id=c1.id, project_id=p3.id, employee_id=None,
            text_content="Cannot upload PDF documents for patient records.",
            predicted_category="Backend Error", priority="HIGH", status="NEW",
            eta=None,
            suggested_action=None,
            created_at=datetime.utcnow() - timedelta(minutes=15)
        )
        db.add_all([t1, t2, t3])
        db.commit()

        # Seed Interactions for Timeline Bug Fix
        db.add(Interaction(customer_id=c1.id, complaint_id=t1.id, role="user", content="Users are bypassing 2FA on the login screen.", timestamp=t1.created_at))
        db.add(Interaction(customer_id=c1.id, complaint_id=t1.id, role="assistant", content="This is a critical security issue. I have escalated this immediately to our Security Analyst, Diana. Expected resolution is 1 hour.", timestamp=t1.created_at + timedelta(minutes=1)))
        
        db.add(Interaction(customer_id=c2.id, complaint_id=t2.id, role="user", content="The checkout button is misaligned on mobile.", timestamp=t2.created_at))
        db.add(Interaction(customer_id=c2.id, complaint_id=t2.id, role="assistant", content="I have notified our Frontend team. Meanwhile, clearing your cache might resolve older cached stylesheets.", timestamp=t2.created_at + timedelta(minutes=5)))
        
        db.add(Interaction(customer_id=c1.id, complaint_id=t3.id, role="user", content="Cannot upload PDF documents for patient records.", timestamp=t3.created_at))
        db.commit()
    
    db.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized.")
