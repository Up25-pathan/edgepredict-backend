import subprocess, json, uuid, os, shutil, asyncio
from typing import List, Optional
from fastapi import Depends, FastAPI, HTTPException, UploadFile, File, Form, status, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from fastapi.responses import FileResponse
import crud, models, schemas, security
from database import SessionLocal, engine
from datetime import timedelta, datetime 
from worker import run_simulation_task
from dotenv import load_dotenv
import httpx

load_dotenv()
models.Base.metadata.create_all(bind=engine)
app = FastAPI()

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

oauth2_scheme = models.oauth2_scheme

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> models.User:
    credentials_exception = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials", headers={"WWW-Authenticate": "Bearer"})
    email = security.decode_access_token(token)
    if email is None: raise credentials_exception
    user = crud.get_user_by_email(db, email=email)
    if user is None: raise credentials_exception
    if not user.is_admin and user.subscription_expiry and user.subscription_expiry < datetime.now():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Subscription expired.")
    return user

async def get_current_admin_user(current_user: models.User = Depends(get_current_user)) -> models.User:
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied.")
    return current_user

# --- Auth/Admin Endpoints (Simplified for brevity, assume standard implementation) ---
@app.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = crud.get_user_by_email(db, email=form_data.username)
    if not user or not security.verify_password(form_data.password, user.hashed_password, user.salt):
        raise HTTPException(status_code=401, detail="Incorrect credentials")
    return {"access_token": security.create_access_token(data={"sub": user.email}), "token_type": "bearer"}

@app.get("/users/me/", response_model=schemas.User)
async def me(current_user: models.User = Depends(get_current_user)): return current_user

# --- Simulation Endpoint (With FIXES) ---
@app.post("/simulations/", response_model=schemas.Simulation, tags=["Simulations"])
def create_simulation(
    payload: schemas.SimulationRequest, 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    db_simulation = models.Simulation(
        name=payload.name,
        description=payload.description,
        status="PENDING",
        owner_id=current_user.id,
        tool_id=payload.tool_id,
        material_id=payload.material_id
    )
    db.add(db_simulation)
    db.commit()
    db.refresh(db_simulation)

    RUNS_BASE_DIR = "simulation_runs"
    run_dir = os.path.join(RUNS_BASE_DIR, f"sim_{db_simulation.id}")
    if os.path.exists(run_dir): shutil.rmtree(run_dir)
    os.makedirs(run_dir, exist_ok=True)
    
    db_tool = db.query(models.Tool).filter(models.Tool.id == payload.tool_id).first()
    if not db_tool: raise HTTPException(403, "Invalid tool")
    
    tool_filename = os.path.basename(db_tool.file_path)
    shutil.copy(db_tool.file_path, os.path.join(run_dir, tool_filename))

    db_material = db.query(models.Material).filter(models.Material.id == payload.material_id).first()
    material_props = json.loads(db_material.properties) if isinstance(db_material.properties, str) else db_material.properties

    engine_payload = {
        "machining_type": payload.machining_type,
        "simulation_parameters": payload.simulation_parameters.dict(),
        "physics_parameters": {}, 
        "material_properties": material_props,
        "file_paths": { "tool_geometry": tool_filename, "output_results": "output.json" }
    }

    if payload.machining_type == "milling":
        engine_payload["milling_params"] = payload.milling_params.dict()
        
        # FIX: Shift workpiece DOWN by 12mm
        wp = payload.workpiece_setup.dict()
        wp["min_corner"][2] -= 0.012
        wp["max_corner"][2] -= 0.012
        engine_payload["workpiece_setup"] = wp
        
        # Intelligent Scaling
        lx = abs(wp["max_corner"][0] - wp["min_corner"][0])
        ly = abs(wp["max_corner"][1] - wp["min_corner"][1])
        lz = abs(wp["max_corner"][2] - wp["min_corner"][2])
        volume = lx * ly * lz
        
        target_particles = 4000
        optimal_spacing = (volume / target_particles) ** (1/3) if volume > 0 else 0.001
        
        sph_params = payload.sph_parameters.dict() if payload.sph_parameters else {}
        sph_params["smoothing_radius_m"] = optimal_spacing * 2.0
        sph_params.setdefault("gas_stiffness", 3000.0)
        sph_params.setdefault("viscosity", 0.01)
        engine_payload["sph_parameters"] = sph_params
        
        physics_defaults = payload.milling_params.dict()
        physics_defaults.update({
            "strain_rate": 1.0,  
            "heat_transfer_coefficient": 100.0,
            "sliding_velocity_m_s": 0.0,
            "strain_increment_per_step": 0.0
        })
        engine_payload["physics_parameters"] = physics_defaults
        
    elif payload.machining_type == "turning":
        engine_payload["turning_params"] = payload.turning_params.dict()
        engine_payload["legacy_cfd_parameters"] = payload.legacy_cfd_parameters.dict()
        engine_payload["physics_parameters"] = {
            "strain_rate": payload.turning_params.strain_rate,
            "sliding_velocity_m_s": payload.turning_params.sliding_velocity_m_s,
            "ambient_temperature_C": payload.turning_params.ambient_temperature_C,
            "strain_increment_per_step": 0.01,
            "heat_transfer_coefficient": 100.0
        }

    with open(os.path.join(run_dir, "input.json"), "w") as f:
        json.dump(engine_payload, f, indent=4)

    run_simulation_task.delay(db_simulation.id, run_dir)
    return db_simulation

# ... (Keep existing read/delete endpoints for simulations, tools, materials) ...
# (I omitted the standard CRUD getters here to keep the response concise, but you should keep them in your file)
@app.get("/simulations/{simulation_id}", response_model=schemas.Simulation)
def read_simulation(simulation_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    db_sim = db.query(models.Simulation).filter(models.Simulation.id == simulation_id).first()
    if not db_sim: raise HTTPException(404, "Simulation not found")
    return db_sim

@app.get("/simulations/", response_model=List[schemas.Simulation])
def read_simulations(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    return db.query(models.Simulation).filter(models.Simulation.owner_id == current_user.id).all()

@app.delete("/simulations/{simulation_id}")
def delete_sim(simulation_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    crud.delete_simulation(db, simulation_id)
    return None

@app.post("/materials/", response_model=schemas.Material)
def create_mat(material: schemas.MaterialCreate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    return crud.create_user_material(db, material, current_user.id)

@app.get("/materials/", response_model=List[schemas.Material])
def get_mats(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    return crud.get_materials_by_user(db, current_user.id)

@app.post("/tools/", response_model=schemas.Tool)
def create_tool_ep(name: str = Form(...), tool_type: str = Form("Other"), file: UploadFile = File(...), db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    path = f"tool_library_files/{uuid.uuid4()}_{file.filename}"
    with open(path, "wb") as f: shutil.copyfileobj(file.file, f)
    return crud.create_user_tool(db, schemas.ToolCreate(name=name, tool_type=tool_type), path, current_user.id)

@app.get("/tools/", response_model=List[schemas.Tool])
def get_tools(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    return crud.get_tools_by_user(db, current_user.id)

@app.get("/tool-file/{tool_id}")
def get_tool_file_ep(tool_id: int, db: Session = Depends(get_db)):
    tool = db.query(models.Tool).filter(models.Tool.id == tool_id).first()
    return FileResponse(tool.file_path) if tool else HTTPException(404)
