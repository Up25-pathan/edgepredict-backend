import subprocess, json, uuid, os, shutil
from typing import List, Optional
from fastapi import Depends, FastAPI, HTTPException, BackgroundTasks, UploadFile, File, Form, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import crud, models, schemas
from database import SessionLocal, engine

models.Base.metadata.create_all(bind=engine)
app = FastAPI()

app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

@app.post("/token", tags=["Authentication"])
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = crud.get_user_by_email(db, email=form_data.username)
    if not user: raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect username or password")
    return {"access_token": user.email, "token_type": "bearer"}

@app.post("/users/", response_model=schemas.User, tags=["Users"])
def create_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    db_user = crud.get_user_by_email(db, email=user.email)
    if db_user: raise HTTPException(status_code=400, detail="Email already registered")
    return crud.create_user(db=db, user=user)

@app.post("/simulations/", response_model=schemas.Simulation, tags=["Simulations"])
def create_simulation(
    background_tasks: BackgroundTasks, name: str = Form(...), description: str = Form(...),
    simulation_parameters: str = Form(...), physics_parameters: str = Form(...), material_properties: str = Form(...),
    tool_id: Optional[int] = Form(None), tool_file: Optional[UploadFile] = File(None), db: Session = Depends(get_db)
):
    if tool_id is None and tool_file is None: raise HTTPException(status_code=400, detail="Tool must be provided.")
    
    db_simulation = crud.create_user_simulation(db=db, simulation=schemas.SimulationCreate(name=name, description=description), user_id=1)
    db.query(models.Simulation).filter(models.Simulation.id == db_simulation.id).update({"material_properties": material_properties})
    
    actual_tool_id = tool_id
    if tool_file:
        new_tool_form_data = schemas.ToolCreate(name=f"{name} (Uploaded)")
        upload_dir = "tool_library_files"; os.makedirs(upload_dir, exist_ok=True)
        file_path = os.path.join(upload_dir, f"{uuid.uuid4()}_{tool_file.filename}")
        with open(file_path, "wb") as buffer: shutil.copyfileobj(tool_file.file, buffer)
        new_db_tool = crud.create_user_tool(db=db, tool=new_tool_form_data, file_path=file_path, user_id=1)
        actual_tool_id = new_db_tool.id
    
    db.query(models.Simulation).filter(models.Simulation.id == db_simulation.id).update({"tool_id": actual_tool_id})
    db.commit()
    
    run_dir = f"temp_run_{uuid.uuid4()}"; os.makedirs(run_dir, exist_ok=True)
    destination_stl_path = os.path.join(run_dir, "tool.stl")
    db_tool = db.query(models.Tool).filter(models.Tool.id == actual_tool_id).first()
    if not db_tool: raise HTTPException(status_code=404, detail="Tool not found.")
    shutil.copy(db_tool.file_path, destination_stl_path)
    
    input_data = {
        "simulation_parameters": json.loads(simulation_parameters),
        "physics_parameters": json.loads(physics_parameters),
        "material_properties": json.loads(material_properties),
        "file_paths": {"tool_geometry": "tool.stl", "output_results": "output.json"}
    }
    with open(os.path.join(run_dir, "input.json"), "w") as f: json.dump(input_data, f, indent=4)
    
    background_tasks.add_task(run_simulation_task, db_simulation.id, run_dir)
    return db_simulation

@app.get("/simulations/", response_model=List[schemas.Simulation], tags=["Simulations"])
def read_simulations(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)): return crud.get_simulations(db, skip=skip, limit=limit)

@app.get("/simulations/{simulation_id}", response_model=schemas.Simulation, tags=["Simulations"])
def read_simulation(simulation_id: int, db: Session = Depends(get_db)):
    db_sim = db.query(models.Simulation).filter(models.Simulation.id == simulation_id).first()
    if not db_sim: raise HTTPException(status_code=404, detail="Simulation not found")
    return db_sim

def run_simulation_task(simulation_id: int, run_dir: str):
    db = SessionLocal()
    try:
        db.query(models.Simulation).filter(models.Simulation.id == simulation_id).update({"status": "RUNNING"}); db.commit()
        docker_command = ["docker", "run", "--rm", "-v", f"{os.path.abspath(run_dir)}:/data", "edgepredict-engine-v2"]
        subprocess.run(docker_command, check=True, capture_output=True, text=True)
        with open(os.path.join(run_dir, "output.json"), "r") as f: results_data = json.load(f)
        db.query(models.Simulation).filter(models.Simulation.id == simulation_id).update({"status": "COMPLETED", "results": json.dumps(results_data)}); db.commit()
    except subprocess.CalledProcessError as e:
        db.query(models.Simulation).filter(models.Simulation.id == simulation_id).update({"status": "FAILED"}); db.commit()
        print(f"Sim failed for ID {simulation_id}. Stderr: {e.stderr}")
    finally: db.close()

@app.get("/materials/", response_model=List[schemas.Material], tags=["Materials"])
def read_materials(db: Session = Depends(get_db)): return crud.get_materials_by_user(db=db, user_id=1)
@app.post("/materials/", response_model=schemas.Material, tags=["Materials"])
def create_material(material: schemas.MaterialCreate, db: Session = Depends(get_db)): return crud.create_user_material(db=db, material=material, user_id=1)

@app.get("/tools/", response_model=List[schemas.Tool], tags=["Tools"])
def read_tools(db: Session = Depends(get_db)): return crud.get_tools_by_user(db=db, user_id=1)
@app.post("/tools/", response_model=schemas.Tool, tags=["Tools"])
def create_tool(name: str = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db)):
    upload_dir = "tool_library_files"; os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, f"{uuid.uuid4()}_{file.filename}")
    with open(file_path, "wb") as f: shutil.copyfileobj(file.file, f)
    return crud.create_user_tool(db=db, tool=schemas.ToolCreate(name=name), file_path=file_path, user_id=1)

@app.get("/tool-file/{tool_id}", tags=["Tools"])
def get_tool_file(tool_id: int, db: Session = Depends(get_db)):
    db_tool = db.query(models.Tool).filter(models.Tool.id == tool_id).first()
    if not db_tool or not os.path.exists(db_tool.file_path): raise HTTPException(status_code=404, detail="Tool file not found.")
    return FileResponse(db_tool.file_path)