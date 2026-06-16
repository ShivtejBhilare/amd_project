import os
from datetime import datetime, timedelta
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

# Ensure the database is created in the backend directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_URL = f"sqlite:///{os.path.join(BASE_DIR, 'cx_routing_v2.db')}"

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
    specialty = Column(String) # e.g., 'GPU Drivers', 'Thermal Management', 'Hardware'
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
        # Add Customers
        c1 = Customer(name="John Doe", email="john@example.com", tier="Premium")
        c2 = Customer(name="Jane Smith", email="jane@example.com", tier="Standard")
        db.add_all([c1, c2])
        
        # Add Employees
        e1 = Employee(name="Alice Walker", specialty="GPU Drivers", is_available=True)
        e2 = Employee(name="Bob Thermal", specialty="Thermal Management", is_available=False)
        e3 = Employee(name="Charlie Spark", specialty="Hardware Replacements", is_available=True)
        e4 = Employee(name="Diana Core", specialty="CPU Performance", is_available=True)
        db.add_all([e1, e2, e3, e4])
        
        # Add Projects
        p1 = Project(name="Radeon RX 7900 XTX")
        p2 = Project(name="Ryzen 9 7950X")
        p3 = Project(name="AMD Adrenalin Software")
        db.add_all([p1, p2, p3])
        
        db.commit() # commit to get IDs
        
        # Add Dummy Tickets
        t1 = Complaint(
            customer_id=c1.id, project_id=p2.id, employee_id=e2.id,
            text_content="My CPU is hitting 95C under load.",
            predicted_category="Thermal", priority="HIGH", status="ASSIGNED",
            suggested_action="Requested cooling setup details.",
            created_at=datetime.utcnow() - timedelta(hours=2)
        )
        t2 = Complaint(
            customer_id=c2.id, project_id=p1.id, employee_id=e1.id,
            text_content="Screen flickers when playing games.",
            predicted_category="Driver", priority="MEDIUM", status="RESOLVED",
            suggested_action="Customer instructed to use AMD Cleanup Utility and reinstall drivers. Issue fixed.",
            created_at=datetime.utcnow() - timedelta(days=1)
        )
        t3 = Complaint(
            customer_id=c1.id, project_id=p3.id, employee_id=None,
            text_content="Adrenalin software won't open after the latest Windows update.",
            predicted_category="Software", priority="LOW", status="RESOLVED",
            suggested_action="Provided self-service steps to restart the AMD External Events Utility service.",
            created_at=datetime.utcnow() - timedelta(days=2)
        )
        db.add_all([t1, t2, t3])
        db.commit()
    
    db.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized.")
