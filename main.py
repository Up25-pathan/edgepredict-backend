import subprocess, json, uuid, os, shutil, asyncio
from typing import List, Optional
from fastapi import Depends, FastAPI, HTTPException, UploadFile, File, Form, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from fastapi.responses import FileResponse
import crud, models, schemas, security
from database import SessionLocal, engine
# --- IMPORT datetime from datetime ---
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
    
    # --- FIX: Use naive datetime ---
    if not user.is_admin and user.subscription_expiry and user.subscription_expiry < datetime.now():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Subscription expired.")
        
    return user

async def get_current_admin_user(current_user: models.User = Depends(get_current_user)) -> models.User:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this resource."
        )
    return current_user

# --- Auth Endpoints ---

@app.post("/token", tags=["Authentication"])
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = crud.get_user_by_email(db, email=form_data.username)
    if not user or not security.verify_password(form_data.password, user.hashed_password, user.salt):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect username or password", headers={"WWW-Authenticate": "Bearer"})

    # --- FIX: Use naive datetime ---
    if not user.is_admin and user.subscription_expiry and user.subscription_expiry < datetime.now():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Your subscription has expired. Please contact support.")

    access_token = security.create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/users/me/", response_model=schemas.User, tags=["Users"])
async def read_users_me(current_user: models.User = Depends(get_current_user)):
    return current_user

# --- Access Request Endpoints ---

@app.post("/request-access", response_model=schemas.AccessRequest, tags=["Public"])
def submit_access_request(request: schemas.AccessRequestCreate, db: Session = Depends(get_db)):
    return crud.create_access_request(db=db, request=request)

@app.get("/admin/access-requests", response_model=List[schemas.AccessRequest], tags=["Admin"])
def get_access_requests(
    skip: int = 0, 
    limit: int = 100, 
    db: Session = Depends(get_db), 
    admin: models.User = Depends(get_current_admin_user)
):
    return crud.get_access_requests(db, skip=skip, limit=limit)

@app.patch("/admin/access-requests/{request_id}", response_model=schemas.AccessRequest, tags=["Admin"])
def update_access_request_status(
    request_id: int,
    status: str, 
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_current_admin_user)
):
    return crud.update_access_request_status(db, request_id, status)

# --- Admin User Management Endpoints ---

@app.post("/admin/users/", response_model=schemas.User, tags=["Admin"])
def admin_create_user(
    user: schemas.AdminUserCreate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_current_admin_user)
):
    db_user = crud.get_user_by_email(db, email=user.email)
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    return crud.admin_create_user(db=db, user=user)

@app.get("/admin/users/", response_model=List[schemas.User], tags=["Admin"])
def admin_get_all_users(
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_current_admin_user)
):
    return crud.get_users(db)

@app.patch("/admin/users/{user_id}", response_model=schemas.User, tags=["Admin"])
def admin_update_user_details(
    user_id: int,
    user_update: schemas.AdminUserUpdate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_current_admin_user)
):
    db_user = crud.admin_update_user(db, user_id=user_id, user_update=user_update)
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return db_user

@app.post("/admin/users/{user_id}/reset-password", response_model=schemas.User, tags=["Admin"])
def admin_reset_user_password(
    user_id: int,
    password_reset: schemas.AdminUserPasswordReset, # <--- CORRECT
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_current_admin_user)
):
    db_user = crud.admin_reset_user_password(db, user_id=user_id, new_password=password_reset.new_password)
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return db_user
    
@app.delete("/admin/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Admin"])
def admin_delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_current_admin_user)
):
    if admin.id == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account.")
        
    db_user = crud.delete_user(db, user_id=user_id)
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return None

# --- Simulation / Tool / Material Endpoints (Existing) ---

@app.post("/simulations/", response_model=schemas.Simulation, tags=["Simulations"])
def create_simulation(name: str = Form(...), description: str = Form(...), simulation_parameters: str = Form(...), physics_parameters: str = Form(...), material_properties: str = Form(...), cfd_parameters: str = Form(...), tool_id: Optional[int] = Form(None), tool_file: Optional[UploadFile] = File(None), db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if tool_id is None and tool_file is None: raise HTTPException(status_code=400, detail="Tool must be provided.")
    try:
        db_simulation = crud.create_user_simulation(db=db, simulation=schemas.SimulationCreate(name=name, description=description), user_id=current_user.id)
        db.query(models.Simulation).filter(models.Simulation.id == db_simulation.id).update({"material_properties": material_properties})
        db.flush()
    except Exception as e: db.rollback(); raise HTTPException(status_code=500, detail=f"Failed to create simulation record: {e}")

    actual_tool_id = tool_id
    tool_filename = None
    if tool_file:
        upload_dir = "tool_library_files"; os.makedirs(upload_dir, exist_ok=True)
        safe_filename = f"{uuid.uuid4()}_{tool_file.filename.replace('..', '').replace('/', '').replace('\\', '')}"
        file_path = os.path.join(upload_dir, safe_filename)
        try:
            with open(file_path, "wb") as buffer: shutil.copyfileobj(tool_file.file, buffer)
            new_db_tool = crud.create_user_tool(db=db, tool=schemas.ToolCreate(name=f"{name} (Uploaded)", tool_type="Other"), file_path=file_path, user_id=current_user.id)
            actual_tool_id = new_db_tool.id
        except Exception as e:
            db.rollback(); 
            if os.path.exists(file_path): os.remove(file_path)
            raise HTTPException(status_code=500, detail=f"Failed to process uploaded tool: {e}")

    try:
        db.query(models.Simulation).filter(models.Simulation.id == db_simulation.id).update({"tool_id": actual_tool_id})
        db.commit()
    except Exception as e: db.rollback(); raise HTTPException(status_code=500, detail=f"Failed to link tool: {e}")

    RUNS_BASE_DIR = "simulation_runs"; os.makedirs(RUNS_BASE_DIR, exist_ok=True)
    run_dir = os.path.join(RUNS_BASE_DIR, f"sim_{db_simulation.id}")
    if os.path.exists(run_dir): shutil.rmtree(run_dir)
    os.makedirs(run_dir, exist_ok=True)
    
    db_tool = db.query(models.Tool).filter(models.Tool.id == actual_tool_id).first()
    if not db_tool or db_tool.owner_id != current_user.id: raise HTTPException(status_code=403, detail="Invalid tool selected.")
    tool_filename = tool_filename or os.path.basename(db_tool.file_path)
    try: shutil.copy(db_tool.file_path, os.path.join(run_dir, tool_filename))
    except Exception as e: shutil.rmtree(run_dir); raise HTTPException(status_code=500, detail=f"Tool copy failed: {e}")

    try:
        try: cfd_params_dict = json.loads(cfd_parameters)
        except: cfd_params_dict = {}
        cfd_params_dict["enable_cfd"] = True
        with open(os.path.join(run_dir, "input.json"), "w") as f:
            json.dump({
                "simulation_parameters": json.loads(simulation_parameters),
                "physics_parameters": json.loads(physics_parameters),
                "material_properties": json.loads(material_properties),
                "cfd_parameters": cfd_params_dict,
                "file_paths": {"tool_geometry": tool_filename, "output_results": "output.json"}
            }, f, indent=4)
    except Exception as e: shutil.rmtree(run_dir); raise HTTPException(status_code=500, detail=f"Input generation failed: {e}")

    try: run_simulation_task.delay(db_simulation.id, run_dir)
    except Exception as e:
         shutil.rmtree(run_dir)
         db.query(models.Simulation).filter(models.Simulation.id == db_simulation.id).update({"status": "FAILED"})
         db.commit()
         raise HTTPException(status_code=500, detail=f"Celery task failed: {e}")

    db.refresh(db_simulation); return db_simulation

@app.get("/simulations/{simulation_id}/progress", tags=["Simulations"])
def get_simulation_progress(simulation_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    db_sim = db.query(models.Simulation).filter(models.Simulation.id == simulation_id).first()
    if not db_sim or db_sim.owner_id != current_user.id: raise HTTPException(status_code=403, detail="Not authorized")
    if db_sim.status in ["COMPLETED", "FAILED"]: return {"status": db_sim.status, "progress_percentage": 100 if db_sim.status == "COMPLETED" else 0}
    progress_file = os.path.join("simulation_runs", f"sim_{simulation_id}", "progress.json")
    if os.path.exists(progress_file):
        try:
            with open(progress_file, 'r') as f: return json.load(f)
        except: return {"status": "RUNNING", "progress_percentage": 0}
    return {"status": "STARTING", "progress_percentage": 0}

@app.get("/simulations/", response_model=List[schemas.Simulation], tags=["Simulations"])
def read_simulations(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    return db.query(models.Simulation).filter(models.Simulation.owner_id == current_user.id).all()

@app.get("/simulations/{simulation_id}", response_model=schemas.Simulation, tags=["Simulations"])
def read_simulation(simulation_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    db_sim = db.query(models.Simulation).filter(models.Simulation.id == simulation_id).first()
    if not db_sim or db_sim.owner_id != current_user.id: raise HTTPException(status_code=403, detail="Not authorized")
    return db_sim

@app.post("/simulations/{simulation_id}/analyze", tags=["Simulations"])
async def analyze_simulation(simulation_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    db_sim = db.query(models.Simulation).filter(models.Simulation.id == simulation_id).first()
    if not db_sim or db_sim.owner_id != current_user.id: raise HTTPException(status_code=403, detail="Not authorized")
    if not db_sim.results: raise HTTPException(status_code=404, detail="Results not ready.")

    try:
        results = json.loads(db_sim.results)
        if results.get("ai_analysis"): return {"analysis": results["ai_analysis"]}

        ts = results.get("time_series_data", [])
        if not ts: raise HTTPException(status_code=404, detail="No time-series data.")

        metrics = {
            "life_hours": results.get("tool_life_prediction", {}).get("predicted_hours", 0),
            "max_temp_C": max((s.get("max_temperature_C", 0) or 0) for s in ts),
            "max_stress_MPa": max((s.get("max_stress_MPa", 0) or 0) for s in ts),
            "wear_microns": max((s.get("total_accumulated_wear_m", 0) or 0) for s in ts) * 1e6
        }
        
        analysis = await get_ai_analysis(json.dumps(ts), metrics)
        
        if not analysis.startswith("Error:"):
            results["ai_analysis"] = analysis
            db_sim.results = json.dumps(results)
            db.commit()
        return {"analysis": analysis}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Report generation failed: {e}")
    
# --- NEW: Delete Simulation Endpoint ---
@app.delete("/simulations/{simulation_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Simulations"])
def delete_simulation(
    simulation_id: int, 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    # 1. Check existence
    db_sim = db.query(models.Simulation).filter(models.Simulation.id == simulation_id).first()
    if not db_sim:
        raise HTTPException(status_code=404, detail="Simulation not found")
    
    # 2. Check ownership
    if not current_user.is_admin and db_sim.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this simulation")

    # 3. Delete files from disk
    run_dir = os.path.join("simulation_runs", f"sim_{simulation_id}")
    if os.path.exists(run_dir):
        try:
            shutil.rmtree(run_dir) # Recursively delete folder
        except Exception as e:
            print(f"Error deleting simulation files: {e}")

    # 4. Delete from DB
    crud.delete_simulation(db=db, simulation_id=simulation_id)
    return None
# ---------------------------------------    

@app.get("/materials/", response_model=List[schemas.Material], tags=["Materials"])
def read_materials(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    return crud.get_materials_by_user(db=db, user_id=current_user.id)

@app.post("/materials/", response_model=schemas.Material, tags=["Materials"])
def create_material(material: schemas.MaterialCreate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    return crud.create_user_material(db=db, material=material, user_id=current_user.id)

@app.get("/tools/", response_model=List[schemas.Tool], tags=["Tools"])
def read_tools(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    return crud.get_tools_by_user(db=db, user_id=current_user.id)

@app.post("/tools/", response_model=schemas.Tool, tags=["Tools"])
def create_tool(name: str = Form(...), tool_type: Optional[str] = Form("Other"), file: UploadFile = File(...), db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    upload_dir = "tool_library_files"; os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, f"{uuid.uuid4()}_{file.filename}")
    try:
        with open(file_path, "wb") as f: shutil.copyfileobj(file.file, f)
        return crud.create_user_tool(db=db, tool=schemas.ToolCreate(name=name, tool_type=tool_type), file_path=file_path, user_id=current_user.id)
    except:
        if os.path.exists(file_path): os.remove(file_path)
        raise HTTPException(status_code=500, detail="Tool upload failed.")

@app.get("/tool-file/{tool_id}", tags=["Tools"])
def get_tool_file(tool_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    db_tool = db.query(models.Tool).filter(models.Tool.id == tool_id).first()
    if not db_tool or not os.path.exists(db_tool.file_path) or db_tool.owner_id != current_user.id: raise HTTPException(status_code=404, detail="Tool file not found.")
    return FileResponse(db_tool.file_path)

@app.delete("/tools/{tool_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Tools"])
def delete_tool(tool_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    db_tool = db.query(models.Tool).filter(models.Tool.id == tool_id).first()
    if not db_tool or db_tool.owner_id != current_user.id: raise HTTPException(status_code=404, detail="Tool not found.")
    if os.path.exists(db_tool.file_path): os.remove(db_tool.file_path)
    crud.delete_tool(db=db, tool_id=tool_id); return None
