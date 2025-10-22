from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, JSON
from sqlalchemy.orm import relationship
from database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    is_active = Column(Boolean, default=True)
    simulations = relationship("Simulation", back_populates="owner")
    materials = relationship("Material", back_populates="owner")
    tools = relationship("Tool", back_populates="owner")

class Simulation(Base):
    __tablename__ = "simulations"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    description = Column(String, index=True)
    status = Column(String, default="PENDING")
    results = Column(String, nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"))
    tool_id = Column(Integer, ForeignKey("tools.id"), nullable=True)
    material_properties = Column(String, nullable=True)
    owner = relationship("User", back_populates="simulations")

class Material(Base):
    __tablename__ = "materials"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    properties = Column(JSON)
    owner_id = Column(Integer, ForeignKey("users.id"))
    owner = relationship("User", back_populates="materials")

class Tool(Base):
    __tablename__ = "tools"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    file_path = Column(String, nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"))
    owner = relationship("User", back_populates="tools")