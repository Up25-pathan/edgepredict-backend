from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# --- NEW: PostgreSQL Connection String ---
# Replace these with your actual database credentials
DB_USER = "postgres"
DB_PASSWORD = "12345678"  # <-- THIS IS THE LINE TO FIX
DB_HOST = "localhost"
DB_PORT = "5432"
DB_NAME = "edgepredict_db"

SQLALCHEMY_DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# --- REMOVED: Old SQLite Connection String ---
# SQLALCHEMY_DATABASE_URL = "sqlite:///./sql_app.db"

# The 'connect_args' was only for SQLite and is no longer needed
engine = create_engine(SQLALCHEMY_DATABASE_URL)

# --- No other changes needed below this line ---

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()
