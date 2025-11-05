from sqlalchemy import Boolean, Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    salt = Column(String)
    # --- THIS LINE WAS REMOVED ---
    # is_active = Column(Boolean, default=True) 

    # Relationships
    simulations = relationship("Simulation", back_populates="owner")
    materials = relationship("Material", back_populates="owner")
    tools = relationship("Tool", back_populates="owner")

class Simulation(Base):
    __tablename__ = "simulations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    description = Column(String)
    status = Column(String, default="PENDING")
    results = Column(String, nullable=True) # Storing results as a JSON string
    material_properties = Column(String, nullable=True) # Storing material JSON string
    
    owner_id = Column(Integer, ForeignKey("users.id"))
    tool_id = Column(Integer, ForeignKey("tools.id"), nullable=True) # Can now be null initially

    owner = relationship("User", back_populates="simulations")
    tool = relationship("Tool") # One-way relationship from Simulation to Tool is fine

class Material(Base):
    __tablename__ = "materials"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    properties = Column(String)  # Storing properties as a JSON string
    owner_id = Column(Integer, ForeignKey("users.id"))

    owner = relationship("User", back_populates="materials")

class Tool(Base):
    __tablename__ = "tools"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    tool_type = Column(String) # e.g., "End Mill", "Drill"
    file_path = Column(String, unique=True) # Path to the .stl or .step file
    owner_id = Column(Integer, ForeignKey("users.id"))

    owner = relationship("User", back_populates="tools")
