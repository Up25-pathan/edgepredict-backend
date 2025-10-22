from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Replace with your actual database connection string in a real application
SQLALCHEMY_DATABASE_URL = "postgresql://user:password@postgresserver/db"

# NOTE: For now, we will use SQLite for simplicity, as it requires no setup.
# This allows us to build the logic without needing to install and configure PostgreSQL yet.
SQLALCHEMY_DATABASE_URL = "sqlite:///./sql_app.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False} # check_same_thread is only for SQLite
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()
