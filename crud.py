import json
from sqlalchemy.orm import Session
import models, schemas, security
import datetime

# --- User CRUD ---

def get_user(db: Session, user_id: int):
    return db.query(models.User).filter(models.User.id == user_id).first()

def get_user_by_email(db: Session, email: str):
    return db.query(models.User).filter(models.User.email == email).first()

def get_users(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.User).offset(skip).limit(limit).all()

def admin_create_user(db: Session, user: schemas.AdminUserCreate):
    salt = security.get_random_salt() 
    hashed_password = security.hash_password(user.password, salt)
    
    expiry_date = None
    if user.subscription_days:
        expiry_date = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=user.subscription_days)
    
    db_user = models.User(
        email=user.email, 
        hashed_password=hashed_password, 
        salt=salt,
        is_admin=user.is_admin,
        subscription_expiry=expiry_date
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def admin_update_user(db: Session, user_id: int, user_update: schemas.AdminUserUpdate):
    db_user = get_user(db, user_id)
    if not db_user:
        return None
    
    update_data = user_update.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_user, key, value)
        
    db.commit()
    db.refresh(db_user)
    return db_user

def admin_reset_user_password(db: Session, user_id: int, new_password: str):
    db_user = get_user(db, user_id)
    if not db_user:
        return None
        
    new_salt = security.get_random_salt()
    new_hashed_password = security.hash_password(new_password, new_salt)
    
    db_user.hashed_password = new_hashed_password
    db_user.salt = new_salt
    
    db.commit()
    return db_user

# --- NEW: Function to delete a user ---
def delete_user(db: Session, user_id: int):
    db_user = get_user(db, user_id)
    if not db_user:
        return None
    
    # Optional: You might want to also delete related simulations, tools, etc.
    # For now, we just delete the user.
    db.delete(db_user)
    db.commit()
    return db_user
# -----------------------------------


# --- Access Request CRUD ---
def create_access_request(db: Session, request: schemas.AccessRequestCreate):
    db_req = models.AccessRequest(
        email=request.email,
        name=request.name,
        company=request.company,
        status="PENDING"
    )
    db.add(db_req)
    db.commit()
    db.refresh(db_req)
    return db_req

def get_access_requests(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.AccessRequest).order_by(models.AccessRequest.request_date.desc()).offset(skip).limit(limit).all()

def update_access_request_status(db: Session, request_id: int, status: str):
    db_req = db.query(models.AccessRequest).filter(models.AccessRequest.id == request_id).first()
    if db_req:
        db_req.status = status
        db.commit()
        db.refresh(db_req)
    return db_req

# --- Simulation CRUD ---
def create_user_simulation(db: Session, simulation: schemas.SimulationCreate, user_id: int):
    db_simulation = models.Simulation(**simulation.dict(), owner_id=user_id)
    db.add(db_simulation)
    db.commit()
    db.refresh(db_simulation)
    return db_simulation

# --- NEW: Delete Simulation ---
def delete_simulation(db: Session, simulation_id: int):
    db_simulation = db.query(models.Simulation).filter(models.Simulation.id == simulation_id).first()
    if db_simulation:
        db.delete(db_simulation)
        db.commit()
        return db_simulation
    return None
# ------------------------------

# --- Material CRUD ---
def get_materials_by_user(db: Session, user_id: int):
    return db.query(models.Material).filter(models.Material.owner_id == user_id).all()

def create_user_material(db: Session, material: schemas.MaterialCreate, user_id: int):
    properties_json_string = json.dumps(material.properties)
    
    db_material = models.Material(
        name=material.name, 
        properties=properties_json_string,
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
