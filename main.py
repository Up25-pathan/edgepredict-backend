import subprocess, json, uuid, os, shutil
from typing import List, Optional
from fastapi import Depends, FastAPI, HTTPException, UploadFile, File, Form, status
# Removed BackgroundTasks - Not needed with Celery
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from sqlalchemy.orm import Session
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import crud, models, schemas, security
from database import SessionLocal, engine
from datetime import timedelta

# Import the Celery task
from worker import run_simulation_celery_task

# Create DB tables if they don't exist
# Note: This won't update existing tables. Use migration tools for that.
models.Base.metadata.create_all(bind=engine)

app = FastAPI()

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"], # Adjust in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Dependency Functions ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> models.User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    email = security.decode_access_token(token)
    if email is None:
        raise credentials_exception
    user = crud.get_user_by_email(db, email=email)
    if user is None:
        raise credentials_exception
    return user
# --- End Dependency Functions ---


# --- Authentication Endpoints ---
@app.post("/token", tags=["Authentication"])
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = crud.get_user_by_email(db, email=form_data.username)
    if not user or not security.verify_password(form_data.password, user.hashed_password, user.salt):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = security.create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/users/", response_model=schemas.User, tags=["Users"])
def create_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    db_user = crud.get_user_by_email(db, email=user.email)
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    return crud.create_user(db=db, user=user)

@app.get("/users/me/", response_model=schemas.User, tags=["Users"])
async def read_users_me(current_user: models.User = Depends(get_current_user)):
    return current_user
# --- End Authentication Endpoints ---


# --- Simulation Endpoints ---
@app.post("/simulations/", response_model=schemas.Simulation, tags=["Simulations"])
def create_simulation(
    name: str = Form(...),
    description: str = Form(...),
    simulation_parameters: str = Form(...),
    physics_parameters: str = Form(...),
    material_properties: str = Form(...),
    tool_id: Optional[int] = Form(None),
    tool_file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if tool_id is None and tool_file is None:
        raise HTTPException(status_code=400, detail="Tool must be provided (either selected ID or uploaded file).")

    # --- Create Simulation Record ---
    try:
        db_simulation = crud.create_user_simulation(db=db, simulation=schemas.SimulationCreate(name=name, description=description), user_id=current_user.id)
        # Update material properties (consider adding to SimulationCreate)
        db.query(models.Simulation).filter(models.Simulation.id == db_simulation.id).update({"material_properties": material_properties})
        db.flush() # Ensure simulation ID is available
    except Exception as e:
         db.rollback()
         print(f"Error creating simulation record: {e}")
         raise HTTPException(status_code=500, detail=f"Failed to create simulation record: {e}")


    actual_tool_id = tool_id
    # --- Handle Tool Upload (if provided) ---
    if tool_file:
        # Note: tool_type would typically be part of the upload form as well
        new_tool_form_data = schemas.ToolCreate(name=f"{name} (Uploaded Tool)", tool_type="Other") # Default type for now
        upload_dir = "tool_library_files"; os.makedirs(upload_dir, exist_ok=True)
        safe_filename = file.filename.replace("..", "").replace("/", "").replace("\\", "")
        file_path = os.path.join(upload_dir, f"{uuid.uuid4()}_{safe_filename}")

        try:
            with open(file_path, "wb") as buffer: shutil.copyfileobj(tool_file.file, buffer)
            new_db_tool = crud.create_user_tool(db=db, tool=new_tool_form_data, file_path=file_path, user_id=current_user.id)
            actual_tool_id = new_db_tool.id
        except Exception as e:
            db.rollback()
            # Clean up uploaded file if DB operation failed
            if os.path.exists(file_path): os.remove(file_path)
            print(f"Error handling uploaded tool: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to process uploaded tool file: {e}")

    # --- Update Simulation with Tool ID ---
    try:
        db.query(models.Simulation).filter(models.Simulation.id == db_simulation.id).update({"tool_id": actual_tool_id})
        db.commit() # Commit simulation creation and tool ID update
    except Exception as e:
        db.rollback()
        print(f"Error updating simulation with tool ID: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to link tool to simulation: {e}")


    # --- Prepare Run Directory ---
    run_dir = f"temp_run_{uuid.uuid4()}"; os.makedirs(run_dir, exist_ok=True)
    destination_stl_path = os.path.join(run_dir, "tool.stl")

    db_tool = db.query(models.Tool).filter(models.Tool.id == actual_tool_id).first()
    if not db_tool:
        # This shouldn't happen if commit was successful, but check anyway
        raise HTTPException(status_code=404, detail=f"Tool with ID {actual_tool_id} not found after linking.")

    if db_tool.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to use the selected tool.")

    try:
        shutil.copy(db_tool.file_path, destination_stl_path)
    except Exception as e:
        if os.path.exists(run_dir): shutil.rmtree(run_dir) # Clean up run dir on copy error
        raise HTTPException(status_code=500, detail=f"Failed to copy tool file to run directory: {e}")

    # --- Create input.json ---
    try:
        input_data = {
            "simulation_parameters": json.loads(simulation_parameters),
            "physics_parameters": json.loads(physics_parameters),
            "material_properties": json.loads(material_properties),
            "file_paths": {"tool_geometry": "tool.stl", "output_results": "output.json"}
        }
        with open(os.path.join(run_dir, "input.json"), "w") as f: json.dump(input_data, f, indent=4)
    except json.JSONDecodeError:
        if os.path.exists(run_dir): shutil.rmtree(run_dir)
        raise HTTPException(status_code=400, detail="Invalid JSON format provided for parameters.")
    except Exception as e:
        if os.path.exists(run_dir): shutil.rmtree(run_dir)
        raise HTTPException(status_code=500, detail=f"Failed to create input.json: {e}")

    # --- Dispatch to Celery ---
    try:
        # Send task to Celery queue
        run_simulation_celery_task.delay(db_simulation.id, run_dir)
        print(f"Sent simulation task to Celery for ID: {db_simulation.id}")
    except Exception as e:
         # If sending to Celery fails, try to clean up and mark simulation as failed
         print(f"Error sending task to Celery: {e}")
         if os.path.exists(run_dir): shutil.rmtree(run_dir)
         try:
              db.query(models.Simulation).filter(models.Simulation.id == db_simulation.id).update({"status": "FAILED"})
              db.commit()
         except Exception as db_err:
              print(f"Failed to mark simulation {db_simulation.id} as FAILED after Celery error: {db_err}")
              db.rollback()
         raise HTTPException(status_code=500, detail=f"Failed to queue simulation task: {e}")


    # Refresh and return the simulation object (status is likely still PENDING)
    db.refresh(db_simulation)
    return db_simulation


@app.get("/simulations/", response_model=List[schemas.Simulation], tags=["Simulations"])
def read_simulations(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    return db.query(models.Simulation).filter(models.Simulation.owner_id == current_user.id).all()


@app.get("/simulations/{simulation_id}", response_model=schemas.Simulation, tags=["Simulations"])
def read_simulation(simulation_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    db_sim = db.query(models.Simulation).filter(models.Simulation.id == simulation_id).first()
    if not db_sim:
        raise HTTPException(status_code=404, detail="Simulation not found")
    if db_sim.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to view this simulation")
    return db_sim
# --- End Simulation Endpoints ---


# --- Material Endpoints ---
@app.get("/materials/", response_model=List[schemas.Material], tags=["Materials"])
def read_materials(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    return crud.get_materials_by_user(db=db, user_id=current_user.id)

@app.post("/materials/", response_model=schemas.Material, tags=["Materials"])
def create_material(material: schemas.MaterialCreate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    return crud.create_user_material(db=db, material=material, user_id=current_user.id)
# --- End Material Endpoints ---


# --- Tool Endpoints ---
@app.get("/tools/", response_model=List[schemas.Tool], tags=["Tools"])
def read_tools(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    return crud.get_tools_by_user(db=db, user_id=current_user.id)

@app.post("/tools/", response_model=schemas.Tool, tags=["Tools"])
def create_tool(
    name: str = Form(...),
    # --- Accept tool_type ---
    tool_type: Optional[str] = Form("Other"), # Default to "Other" if not provided
    # --- End Accept ---
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    upload_dir = "tool_library_files"; os.makedirs(upload_dir, exist_ok=True)
    safe_filename = file.filename.replace("..", "").replace("/", "").replace("\\", "")
    file_path = os.path.join(upload_dir, f"{uuid.uuid4()}_{safe_filename}")

    try:
        with open(file_path, "wb") as f: shutil.copyfileobj(file.file, f)
    except Exception as e:
        print(f"Error saving uploaded file: {e}")
        raise HTTPException(status_code=500, detail="Could not save uploaded tool file.")

    # --- Pass tool_type to schema ---
    tool_data = schemas.ToolCreate(name=name, tool_type=tool_type)
    # --- End Pass ---

    try:
        # Call crud function which now handles tool_type
        return crud.create_user_tool(db=db, tool=tool_data, file_path=file_path, user_id=current_user.id)
    except Exception as e:
        # Clean up file if DB insert fails
        if os.path.exists(file_path): os.remove(file_path)
        print(f"Error creating tool record: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Could not create tool record in database: {e}")


@app.get("/tool-file/{tool_id}", tags=["Tools"])
def get_tool_file(tool_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    db_tool = db.query(models.Tool).filter(models.Tool.id == tool_id).first()
    if not db_tool:
        raise HTTPException(status_code=404, detail="Tool not found.")
    if not os.path.exists(db_tool.file_path):
        raise HTTPException(status_code=404, detail="Tool file not found on server.")
    if db_tool.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to access this file")
    return FileResponse(db_tool.file_path)

# --- NEW: Delete Tool Endpoint ---
@app.delete("/tools/{tool_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Tools"])
def delete_tool(
    tool_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    db_tool = db.query(models.Tool).filter(models.Tool.id == tool_id).first()
    if not db_tool:
        raise HTTPException(status_code=404, detail="Tool not found.")
    if db_tool.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this tool.")

    # Optional: Check if tool is used by any simulations before deleting?
    # is_used = db.query(models.Simulation).filter(models.Simulation.tool_id == tool_id).first()
    # if is_used:
    #     raise HTTPException(status_code=400, detail="Cannot delete tool: It is currently used in simulations.")

    try:
        # Delete file from filesystem first
        if os.path.exists(db_tool.file_path):
            os.remove(db_tool.file_path)

        # Delete from database
        deleted_tool = crud.delete_tool(db=db, tool_id=tool_id)
        if deleted_tool is None: # Should not happen if checks above pass
             raise HTTPException(status_code=404, detail="Tool not found during delete.")
        # Return No Content on success
        return None

    except Exception as e:
         print(f"Error deleting tool {tool_id}: {e}")
         db.rollback() # Rollback DB change if file deletion failed after DB delete started
         raise HTTPException(status_code=500, detail=f"Could not delete tool: {e}")

# --- End Tool Endpoints ---

