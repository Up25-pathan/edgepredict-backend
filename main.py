import subprocess, json, uuid, os, shutil
from typing import List, Optional
from fastapi import Depends, FastAPI, HTTPException, UploadFile, File, Form, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from sqlalchemy.orm import Session
from fastapi.responses import FileResponse
import crud, models, schemas, security
from database import SessionLocal, engine
from datetime import timedelta
from worker import run_simulation_task
from dotenv import load_dotenv
import httpx # For AI Analysis

# Load environment variables
load_dotenv()

# Create DB tables if they don't exist
models.Base.metadata.create_all(bind=engine)

app = FastAPI()

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
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
    cfd_parameters: str = Form(...),
    tool_id: Optional[int] = Form(None),
    tool_file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if tool_id is None and tool_file is None:
        raise HTTPException(status_code=400, detail="Tool must be provided (either selected ID or uploaded file).")

    try:
        db_simulation = crud.create_user_simulation(db=db, simulation=schemas.SimulationCreate(name=name, description=description), user_id=current_user.id)
        db.query(models.Simulation).filter(models.Simulation.id == db_simulation.id).update({"material_properties": material_properties})
        db.flush()
    except Exception as e:
         db.rollback()
         raise HTTPException(status_code=500, detail=f"Failed to create simulation record: {e}")

    actual_tool_id = tool_id
    tool_filename = None

    if tool_file:
        new_tool_form_data = schemas.ToolCreate(name=f"{name} (Uploaded Tool)", tool_type="Other")
        upload_dir = "tool_library_files"; os.makedirs(upload_dir, exist_ok=True)
        safe_filename = tool_file.filename.replace("..", "").replace("/", "").replace("\\", "")
        tool_filename = f"{uuid.uuid4()}_{safe_filename}" 
        file_path = os.path.join(upload_dir, tool_filename)
        try:
            with open(file_path, "wb") as buffer: shutil.copyfileobj(tool_file.file, buffer)
            new_db_tool = crud.create_user_tool(db=db, tool=new_tool_form_data, file_path=file_path, user_id=current_user.id)
            actual_tool_id = new_db_tool.id
        except Exception as e:
            db.rollback()
            if os.path.exists(file_path): os.remove(file_path)
            raise HTTPException(status_code=500, detail=f"Failed to process uploaded tool file: {e}")

    try:
        db.query(models.Simulation).filter(models.Simulation.id == db_simulation.id).update({"tool_id": actual_tool_id})
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to link tool to simulation: {e}")

    RUNS_BASE_DIR = "simulation_runs"
    os.makedirs(RUNS_BASE_DIR, exist_ok=True)
    run_dir = os.path.join(RUNS_BASE_DIR, f"sim_{db_simulation.id}")
    if os.path.exists(run_dir):
        shutil.rmtree(run_dir)
    os.makedirs(run_dir, exist_ok=True)
    
    db_tool = db.query(models.Tool).filter(models.Tool.id == actual_tool_id).first()
    if not db_tool:
        raise HTTPException(status_code=404, detail=f"Tool with ID {actual_tool_id} not found.")
    if db_tool.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to use the selected tool.")
    if not tool_filename:
        tool_filename = os.path.basename(db_tool.file_path)
    destination_tool_path = os.path.join(run_dir, tool_filename)
    try:
        shutil.copy(db_tool.file_path, destination_tool_path)
    except Exception as e:
        if os.path.exists(run_dir): shutil.rmtree(run_dir)
        raise HTTPException(status_code=500, detail=f"Failed to copy tool file to run directory: {e}")

    # --- Create input.json ---
    try:
        try:
            cfd_params_dict = json.loads(cfd_parameters)
        except json.JSONDecodeError:
            cfd_params_dict = {}
        
        # Force-enable CFD for the simulation engine
        cfd_params_dict["enable_cfd"] = True

        input_data = {
            "simulation_parameters": json.loads(simulation_parameters),
            "physics_parameters": json.loads(physics_parameters),
            "material_properties": json.loads(material_properties),
            "cfd_parameters": cfd_params_dict,
            "file_paths": {
                "tool_geometry": tool_filename, 
                "output_results": "output.json"
            }
        }
        with open(os.path.join(run_dir, "input.json"), "w") as f: json.dump(input_data, f, indent=4)
    except json.JSONDecodeError:
        if os.path.exists(run_dir): shutil.rmtree(run_dir)
        raise HTTPException(status_code=400, detail="Invalid JSON format provided for parameters.")
    except Exception as e:
        if os.path.exists(run_dir): shutil.rmtree(run_dir)
        raise HTTPException(status_code=500, detail=f"Failed to create input.json: {e}")

    try:
        run_simulation_task.delay(db_simulation.id, run_dir)
    except Exception as e:
         print(f"Error sending task to Celery: {e}")
         if os.path.exists(run_dir): shutil.rmtree(run_dir)
         try:
              db.query(models.Simulation).filter(models.Simulation.id == db_simulation.id).update({"status": "FAILED"})
              db.commit()
         except Exception as db_err:
              print(f"Failed to mark simulation {db_simulation.id} as FAILED: {db_err}")
              db.rollback()
         raise HTTPException(status_code=500, detail=f"Failed to queue simulation task: {e}")

    db.refresh(db_simulation)
    return db_simulation

@app.get("/simulations/{simulation_id}/progress", tags=["Simulations"])
def get_simulation_progress(
    simulation_id: int, 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    db_sim = db.query(models.Simulation).filter(models.Simulation.id == simulation_id).first()
    if not db_sim:
        raise HTTPException(status_code=404, detail="Simulation not found")
    if db_sim.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    if db_sim.status in ["COMPLETED", "FAILED"]:
        return {"status": db_sim.status, "progress_percentage": 100 if db_sim.status == "COMPLETED" else 0}

    RUNS_BASE_DIR = "simulation_runs"
    progress_file = os.path.join(RUNS_BASE_DIR, f"sim_{simulation_id}", "progress.json")

    if os.path.exists(progress_file):
        try:
            with open(progress_file, 'r') as f:
                return json.load(f)
        except Exception:
            return {"status": "RUNNING", "progress_percentage": 0, "detail": "Waiting for engine update..."}
    else:
        return {"status": "STARTING", "progress_percentage": 0}

@app.get("/simulations/", response_model=List[schemas.Simulation], tags=["Simulations"])
def read_simulations(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    return db.query(models.Simulation).filter(models.Simulation.owner_id == current_user.id).all()

@app.get("/simulations/{simulation_id}", response_model=schemas.Simulation, tags=["Simulations"])
def read_simulation(simulation_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    db_sim = db.query(models.Simulation).filter(models.Simulation.id == simulation_id).first()
    if not db_sim:
        raise HTTPException(status_code=404, detail="Simulation not found")
    if db_sim.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    return db_sim

# --- AI Analysis Endpoint ---
async def get_ai_analysis(results_json: str, peak_metrics: dict):
    """Helper function to call Gemini API"""
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    if not GEMINI_API_KEY:
        return "Error: GEMINI_API_KEY not configured on server."

    API_URL = f"https{os.path.pathsep}//generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-09-2025:generateContent?key={GEMINI_API_KEY}"

    system_prompt = (
        "You are an expert machining and materials science analyst. "
        "Your job is to interpret simulation data and provide actionable recommendations. "
        "A user will provide a JSON object of simulation results. "
        "You must provide your analysis in three sections: "
        "1.  **Summary:** A one-paragraph overview of the tool's performance. "
        "2.  **Key Insights:** A bulleted list of 2-3 critical findings (e.g., 'High thermal load,' 'Rapid flank wear,' 'Risk of fracture'). "
        "3.  **Recommendations:** A bulleted list of 2-3 actionable suggestions for the user (e.g., 'Decrease spindle speed,' 'Increase coolant pressure,' 'Consider a tool with a different coating')."
    )
    
    user_prompt = (
        "Here is my simulation data. Please analyze it and provide your expert report.\n\n"
        f"**Peak Metrics:**\n{json.dumps(peak_metrics, indent=2)}\n\n"
        f"**Full Time-Series (excerpt):**\n{results_json[0:2000]}..."
    )

    payload = {
        "contents": [{"parts": [{"text": user_prompt}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(API_URL, json=payload)
            response.raise_for_status() # Raise an exception for 4xx/5xx errors
            
            data = response.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return text
            
    except httpx.HTTPStatusError as e:
        print(f"HTTP error calling Gemini: {e.response.status_code} - {e.response.text}")
        return f"Error: Failed to get analysis from AI service (HTTP {e.response.status_code})."
    except Exception as e:
        print(f"Error calling Gemini: {e}")
        return f"Error: An unexpected error occurred while generating the AI report: {str(e)}"

@app.post("/simulations/{simulation_id}/analyze", tags=["Simulations"])
async def analyze_simulation(
    simulation_id: int, 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    db_sim = read_simulation(simulation_id, db, current_user)
    
    if not db_sim.results:
        raise HTTPException(status_code=404, detail="No results found for this simulation.")

    try:
        results = json.loads(db_sim.results)
        time_series = results.get("time_series_data", [])
        
        if not time_series:
            raise HTTPException(status_code=404, detail="Time series data is missing from results.")

        # --- THIS IS THE FIX ---
        # The broken JavaScript line has been REMOVED.
        # --- END FIX ---

        # --- PYTHON-BASED PEAK METRICS CALCULATION ---
        peak_temp = 0
        peak_stress = 0
        peak_wear = 0
        peak_fractured = 0
        
        for step in time_series:
            peak_temp = max(peak_temp, step.get("max_temperature_C", 0) or 0)
            peak_stress = max(peak_stress, step.get("max_stress_MPa", 0) or 0)
            peak_wear = max(peak_wear, step.get("total_accumulated_wear_m", 0) or 0)
            peak_fractured = max(peak_fractured, step.get("cumulative_fractured_nodes", 0) or 0)

        ai_prompt_metrics = {
            "predicted_tool_life_hours": results.get("tool_life_prediction", {}).get("predicted_hours", 0),
            "peak_temperature_C": peak_temp,
            "max_stress_MPa": peak_stress,
            "final_wear_m": peak_wear,
            "final_fractured_nodes": peak_fractured
        }
        
        # Get the AI analysis
        analysis_text = await get_ai_analysis(json.dumps(time_series), ai_prompt_metrics)
        return {"analysis": analysis_text}

    except Exception as e:
        print(f"Error in analyze_simulation: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to parse results or generate report: {str(e)}")
# --- End AI Endpoint ---

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
    tool_type: Optional[str] = Form("Other"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    upload_dir = "tool_library_files"; os.makedirs(upload_dir, exist_ok=True)
    safe_filename = file.filename.replace("..", "").replace("/", "").replace("\\", "")
    unique_filename = f"{uuid.uuid4()}_{safe_filename}"
    file_path = os.path.join(upload_dir, unique_filename)

    try:
        with open(file_path, "wb") as f: shutil.copyfileobj(file.file, f)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Could not save uploaded tool file.")

    tool_data = schemas.ToolCreate(name=name, tool_type=tool_type)
    try:
        return crud.create_user_tool(db=db, tool=tool_data, file_path=file_path, user_id=current_user.id)
    except Exception as e:
        if os.path.exists(file_path): os.remove(file_path)
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
        raise HTTPException(status_code=403, detail="Not authorized")
    return FileResponse(db_tool.file_path)

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
        raise HTTPException(status_code=403, detail="Not authorized")
    try:
        if os.path.exists(db_tool.file_path):
            os.remove(db_tool.file_path)
        crud.delete_tool(db=db, tool_id=tool_id)
        return None
    except Exception as e:
         db.rollback()
         raise HTTPException(status_code=500, detail=f"Could not delete tool: {e}")
# --- End Tool Endpoints ---
