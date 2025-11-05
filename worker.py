import subprocess, json, os, shutil
from celery import Celery
from database import SessionLocal
import models

# Configure Celery
# Assumes Redis is running on localhost:6379
celery = Celery(
    'tasks',
    broker='redis://localhost:6379/0',
    backend='redis://localhost:6379/0'
)

# Set Celery to use 'json' serializer
celery.conf.update(
    task_serializer='json',
    result_serializer='json',
    accept_content=['json']
)

@celery.task
def run_simulation_task(simulation_id, run_dir):
    """
    Celery task to run a simulation in a Docker container.
    """
    # Create a new, independent database session for the worker
    db = SessionLocal()
    
    try:
        # --- 1. Get Simulation & Update Status ---
        db_simulation = db.query(models.Simulation).filter(models.Simulation.id == simulation_id).first()
        if not db_simulation:
            print(f"Error: Simulation ID {simulation_id} not found.")
            return

        db_simulation.status = "RUNNING"
        db.commit()

        # --- 2. Run Docker Container ---
        docker_command = [
            "docker", "run", "--rm",
            "-v", f"{os.path.abspath(run_dir)}:/data",
            "edgepredict-engine-v2", # This is the name of your simulation engine Docker image
            "/data/input.json" # Argument passed to the engine's main.cpp
        ]

        print(f"Running command: {' '.join(docker_command)}")
        
        process = subprocess.run(
            docker_command, 
            capture_output=True, 
            text=True,
            encoding='utf-8', 
            errors='ignore',
            cwd=os.path.abspath(run_dir)
        )

        # --- 3. Process Results ---
        if process.returncode == 0:
            print(f"Simulation {simulation_id} completed successfully.")
            output_file_path = os.path.join(run_dir, "output.json")
            
            if os.path.exists(output_file_path):
                with open(output_file_path, 'r') as f:
                    results_json_string = f.read()
                
                db_simulation.status = "COMPLETED"
                db_simulation.results = results_json_string
                db.commit()
            else:
                print(f"Error: output.json not found for simulation {simulation_id}.")
                db_simulation.status = "FAILED"
                db_simulation.results = '{"error": "Simulation ran but output.json was not generated."}'
                db.commit()
        else:
            # Simulation failed
            print(f"Error running simulation {simulation_id}. Return code: {process.returncode}")
            print(f"STDOUT: {process.stdout}")
            print(f"STDERR: {process.stderr}")
            db_simulation.status = "FAILED"
            db_simulation.results = json.dumps({
                "error": "Simulation engine failed to run.",
                "returncode": process.returncode,
                "stdout": process.stdout,
                "stderr": process.stderr
            })
            db.commit()

    except Exception as e:
        print(f"A critical error occurred in the Celery task for simulation {simulation_id}: {e}")
        try:
            db_simulation.status = "FAILED"
            db_simulation.results = json.dumps({"error": f"Celery worker error: {str(e)}"})
            db.commit()
        except Exception as db_e:
            print(f"Failed to even update simulation status to FAILED: {db_e}")
            db.rollback() # Rollback any changes if update fails
            
    finally:
        # --- 4. Clean up Run Directory ---
        
        # --- FIX: RE-ENABLE CLEANUP ---
        if os.path.exists(run_dir):
            try:
                shutil.rmtree(run_dir)
                print(f"Cleaned up {run_dir}")
            except Exception as e:
                print(f"Error cleaning up directory {run_dir}: {e}")
        
        # Always close the session
        db.close()
