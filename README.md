EdgePredict Backend API

This is the central backend service for the EdgePredict SaaS platform. It is a Python-based API built with FastAPI, responsible for user authentication, database management, and dispatching simulation jobs to the C++ engine.

This backend connects the React frontend to the C++ simulation engine via a Celery task queue.

# How to Run the 

To run the entire platform, you must start 4 separate services in 4 separate terminals.

Terminal 1: Start Redis

Start the Redis message broker using Docker.

docker run -d --name edgepredict-redis -p 6379:6379 redis


(If it's already created, just run: docker start edgepredict-redis)

Terminal 2: Start the FastAPI Server

This runs the main API that the React app talks to.

# In the edgepredict-backend folder
.\venv\Scripts\activate
uvicorn main:app --reload


The API will be available at http://127.0.0.1:8000.

Terminal 3: Start the Celery Worker

This is the service that listens for and runs the simulation jobs.

# In the edgepredict-backend folder
.\venv\Scripts\activate
celery -A worker.celery worker --loglevel=info -P solo


(Note: -P solo is recommended for Windows compatibility)

Terminal 4: Start the React Frontend

This serves the user interface.

# In the edgepredict-ui folder
npm start


The app will be available at http://localhost:3000.
