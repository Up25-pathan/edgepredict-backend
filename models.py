from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, DateTime
from sqlalchemy.orm import relationship
from database import Base
import datetime
from fastapi.security import OAuth2PasswordBearer

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    salt = Column(String)
    
    is_admin = Column(Boolean, default=False)
    subscription_expiry = Column(DateTime, nullable=True)

    simulations = relationship("Simulation", back_populates="owner")
    materials = relationship("Material", back_populates="owner")
    tools = relationship("Tool", back_populates="owner")

class AccessRequest(Base):
    __tablename__ = "access_requests"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, index=True)
    name = Column(String)
    company = Column(String)
    status = Column(String, default="PENDING")
    # --- FIX: Use naive datetime ---
    request_date = Column(DateTime, default=datetime.datetime.now)

class Simulation(Base):
    __tablename__ = "simulations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    description = Column(String)
    status = Column(String, default="PENDING")
    results = Column(String, nullable=True)
    material_properties = Column(String, nullable=True)
    
    owner_id = Column(Integer, ForeignKey("users.id"))
    tool_id = Column(Integer, ForeignKey("tools.id"), nullable=True)

    owner = relationship("User", back_populates="simulations")
    tool = relationship("Tool")

class Material(Base):
    __tablename__ = "materials"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    properties = Column(String)
    owner_id = Column(Integer, ForeignKey("users.id"))

    owner = relationship("User", back_populates="materials")

class Tool(Base):
    __tablename__ = "tools"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    tool_type = Column(String)
    file_path = Column(String, unique=True)
    owner_id = Column(Integer, ForeignKey("users.id"))

    owner = relationship("User", back_populates="tools")
