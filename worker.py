import os
import subprocess
import json
import shutil
from celery import Celery

# Import database session, models
from database import SessionLocal
import models # Make sure models are imported so Celery knows about them

# --- Celery Configuration ---
# Use the Redis container we started as the broker and result backend
# The broker holds the queue of tasks waiting to run.
# The backend stores the results of completed tasks (optional but useful).
redis_url = "redis://localhost:6379/0" # /0 selects database 0 in Redis

celery_app = Celery(
    "tasks",            # Name of the Celery application
    broker=redis_url,
    backend=redis_url,
    include=['worker']  # Tells Celery to look for tasks in this file ('worker.py')
)

# Optional Celery configuration settings
celery_app.conf.update(
    task_serializer='json',      # Use json for task messages
    accept_content=['json'],     # Accept json content
    result_serializer='json',    # Use json for results
    timezone='UTC',              # Use UTC timezone
    enable_utc=True,
    broker_connection_retry_on_startup=True # Attempt reconnect if Redis isn't ready immediately
)

# --- Celery Task Definition ---
@celery_app.task(name="run_simulation_task") # Give the task a specific name
def run_simulation_celery_task(simulation_id: int, run_dir: str):
    """
    Celery task to run the simulation engine in Docker.
    This replaces the old FastAPI BackgroundTasks function.
    """
    # Create a new database session specific to this task
    db = SessionLocal()
    try:
        # Check if simulation exists (important as task runs independently)
        sim = db.query(models.Simulation).filter(models.Simulation.id == simulation_id).first()
        if not sim:
             print(f"Error [Celery]: Simulation ID {simulation_id} not found.")
             # Consider raising an error or returning a specific status
             return {"status": "ERROR", "detail": f"Simulation ID {simulation_id} not found."}

        # Update status to RUNNING
        print(f"Starting simulation task for ID: {simulation_id} in dir: {run_dir}")
        db.query(models.Simulation).filter(models.Simulation.id == simulation_id).update({"status": "RUNNING"})
        db.commit()

        # Define and run the Docker command
        docker_command = ["docker", "run", "--rm", "-v", f"{os.path.abspath(run_dir)}:/data", "edgepredict-engine-v2"]
        # Use a reasonable timeout (e.g., 1 hour = 3600 seconds)
        timeout_seconds = 3600
        result = subprocess.run(
            docker_command,
            capture_output=True,
            text=True,
            check=False, # Don't raise error immediately, check returncode instead
            timeout=timeout_seconds
        )

        # Process results based on Docker exit code
        if result.returncode == 0:
            output_file_path = os.path.join(run_dir, "output.json")
            if os.path.exists(output_file_path):
                 with open(output_file_path, "r") as f:
                     results_data = json.load(f)
                 db.query(models.Simulation).filter(models.Simulation.id == simulation_id).update({
                     "status": "COMPLETED",
                     "results": json.dumps(results_data) # Store results as JSON string
                 })
                 print(f"Simulation COMPLETED for ID: {simulation_id}")
                 task_result = {"status": "COMPLETED"}
            else:
                 print(f"Simulation OK for ID {simulation_id} but output.json missing!")
                 db.query(models.Simulation).filter(models.Simulation.id == simulation_id).update({"status": "FAILED"})
                 task_result = {"status": "FAILED", "detail": "Output file missing"}
        else:
            # Docker container failed
            stderr_output = result.stderr or "No stderr captured."
            print(f"Simulation FAILED for ID: {simulation_id}. Code: {result.returncode}. Stderr: {stderr_output}")
            db.query(models.Simulation).filter(models.Simulation.id == simulation_id).update({"status": "FAILED"})
            task_result = {"status": "FAILED", "detail": f"Engine exited with code {result.returncode}. Error: {stderr_output[:500]}"} # Limit error length

        db.commit() # Commit final status update
        return task_result # Return task result

    except subprocess.TimeoutExpired:
        print(f"Simulation TIMED OUT for ID: {simulation_id}")
        db.query(models.Simulation).filter(models.Simulation.id == simulation_id).update({"status": "FAILED"})
        db.commit()
        return {"status": "FAILED", "detail": "Simulation timed out"}
    except Exception as e:
        print(f"Unexpected ERROR during simulation task for ID {simulation_id}: {e}")
        # Rollback any partial changes and set status to FAILED
        db.rollback()
        try:
            # Try one more time to set status to FAILED
            db.query(models.Simulation).filter(models.Simulation.id == simulation_id).update({"status": "FAILED"})
            db.commit()
        except Exception as db_err:
            print(f"CRITICAL: Failed to update simulation status to FAILED for ID {simulation_id} after error: {db_err}")
            db.rollback()
        # It's good practice to re-raise the exception or return detailed error info
        # raise e # Option 1: Re-raise to mark task as failed in Celery monitor
        return {"status": "FAILED", "detail": f"Unexpected error: {str(e)}"} # Option 2: Return error status
    finally:
        db.close() # Ensure the session is closed
        # Clean up temporary run directory
        if os.path.exists(run_dir):
            try:
                shutil.rmtree(run_dir)
                print(f"Cleaned up run directory: {run_dir}")
            except Exception as cleanup_err:
                print(f"Error cleaning up run directory {run_dir}: {cleanup_err}")

# You can add other tasks here if needed

if __name__ == '__main__':
    # This allows running the worker directly (optional)
    # The command line `celery -A worker.celery_app worker --loglevel=info` is preferred
    celery_app.start()