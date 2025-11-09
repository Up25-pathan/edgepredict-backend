import json
from sqlalchemy.orm import Session
import models, schemas, security

# --- User CRUD ---

def get_user(db: Session, user_id: int):
    return db.query(models.User).filter(models.User.id == user_id).first()

def get_user_by_email(db: Session, email: str):
    return db.query(models.User).filter(models.User.email == email).first()

def get_users(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.User).offset(skip).limit(limit).all()

def create_user(db: Session, user: schemas.UserCreate):
    # --- THIS WAS THE BUG ---
    # It was 'security.generate_salt()', but the function is 'get_random_salt'
    salt = security.get_random_salt() 
    # --- END FIX ---
    
    hashed_password = security.hash_password(user.password, salt)
    
    db_user = models.User(
        email=user.email, 
        hashed_password=hashed_password, 
        salt=salt
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

# --- Simulation CRUD ---

def create_user_simulation(db: Session, simulation: schemas.SimulationCreate, user_id: int):
    db_simulation = models.Simulation(**simulation.dict(), owner_id=user_id)
    db.add(db_simulation)
    db.commit()
    db.refresh(db_simulation)
    return db_simulation

# --- Material CRUD ---

def get_materials_by_user(db: Session, user_id: int):
    return db.query(models.Material).filter(models.Material.owner_id == user_id).all()

def create_user_material(db: Session, material: schemas.MaterialCreate, user_id: int):
    # Convert the 'properties' dictionary into a JSON string before saving
    properties_json_string = json.dumps(material.properties)
    
    db_material = models.Material(
        name=material.name, 
        properties=properties_json_string, # Use the string version
        owner_id=user_id
    )
    
    db.add(db_material)
    db.commit()
    db.refresh(db_material)
    return db_material

# --- Tool CRUD ---

def get_tools_by_user(db: Session, user_id: int):
    return db.query(models.Tool).filter(models.Tool.owner_id == user_id).all()

def create_user_tool(db: Session, tool: schemas.ToolCreate, file_path: str, user_id: int):
    db_tool = models.Tool(
        **tool.dict(), 
        file_path=file_path, 
        owner_id=user_id
    )
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
    return None
