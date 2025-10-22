from sqlalchemy.orm import Session
import models
import schemas

# --- User CRUD Functions ---
def get_user(db: Session, user_id: int):
    return db.query(models.User).filter(models.User.id == user_id).first()

def get_user_by_email(db: Session, email: str):
    return db.query(models.User).filter(models.User.email == email).first()

def get_users(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.User).offset(skip).limit(limit).all()

def create_user(db: Session, user: schemas.UserCreate):
    # In a real app, you would hash the password properly.
    fake_hashed_password = user.password + "notreallyhashed"
    db_user = models.User(email=user.email, hashed_password=fake_hashed_password)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

# --- Simulation CRUD Functions ---
def get_simulations(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.Simulation).offset(skip).limit(limit).all()

def create_user_simulation(db: Session, simulation: schemas.SimulationCreate, user_id: int):
    db_simulation = models.Simulation(**simulation.dict(), owner_id=user_id)
    db.add(db_simulation)
    db.commit()
    db.refresh(db_simulation)
    return db_simulation

# --- NEW: Material CRUD Functions ---
def get_materials_by_user(db: Session, user_id: int, skip: int = 0, limit: int = 100):
    return db.query(models.Material).filter(models.Material.owner_id == user_id).offset(skip).limit(limit).all()

def create_user_material(db: Session, material: schemas.MaterialCreate, user_id: int):
    db_material = models.Material(**material.dict(), owner_id=user_id)
    db.add(db_material)
    db.commit()
    db.refresh(db_material)
    return db_material

def delete_material(db: Session, material_id: int):
    db_material = db.query(models.Material).filter(models.Material.id == material_id).first()
    if db_material:
        db.delete(db_material)
        db.commit()
    return db_material

# --- NEW: Tool CRUD Functions ---
def get_tools_by_user(db: Session, user_id: int, skip: int = 0, limit: int = 100):
    return db.query(models.Tool).filter(models.Tool.owner_id == user_id).offset(skip).limit(limit).all()

def create_user_tool(db: Session, tool: schemas.ToolCreate, file_path: str, user_id: int):
    db_tool = models.Tool(name=tool.name, file_path=file_path, owner_id=user_id)
    db.add(db_tool)
    db.commit()
    db.refresh(db_tool)
    return db_tool

def delete_tool(db: Session, tool_id: int):
    db_tool = db.query(models.Tool).filter(models.Tool.id == tool_id).first()
    if db_tool:
        db.delete(db_tool)
        db.commit()
    return db_tool