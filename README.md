This is the Python-based backend for the EdgePredict simulation platform, built with FastAPI.

Setup
Create a Virtual Environment (Recommended)

python -m venv venv
source venv/bin/activate  
`venv\Scripts\activate`  # On Windows, use

Install Dependencies
Install all the required libraries from the requirements.txt file.

pip install -r requirements.txt

Running the Server
To run the development server, use uvicorn. The --reload flag will automatically restart the server whenever you make changes to the code.

uvicorn main:app --reload

The API will be available at http://127.0.0.1:8000.

You can access the interactive API documentation (provided automatically by FastAPI) by navigating to http://127.0.0.1:8000/docs in your browser.

├── database.py         # New: Handles database connection.
├── main.py             # Updated: Will include new /reports endpoints.
├── models.py           # New: Defines our database tables.
├── schemas.py          # New: Defines the shape of our API data.
├── requirements.txt    # Updated: Will add database libraries.
└── README.md