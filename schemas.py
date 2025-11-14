from pydantic import BaseModel, EmailStr
from typing import Optional, Any
import datetime

# --- Tool Schemas ---
class ToolBase(BaseModel):
    name: str
    tool_type: Optional[str] = None

class ToolCreate(ToolBase):
    pass

class Tool(ToolBase):
    id: int
    file_path: str
    owner_id: int

    class Config:
        from_attributes = True

# --- Material Schemas ---
class MaterialBase(BaseModel):
    name: str
    properties: Any

class MaterialCreate(MaterialBase):
    pass

class Material(MaterialBase):
    id: int
    owner_id: int
    properties: str 

    class Config:
        from_attributes = True

# --- Simulation Schemas ---
class SimulationBase(BaseModel):
    name: str
    description: Optional[str] = None

class SimulationCreate(SimulationBase):
    pass

class Simulation(SimulationBase):
    id: int
    owner_id: int
    tool_id: Optional[int] = None
    status: str
    results: Optional[str] = None
    material_properties: Optional[str] = None

    class Config:
        from_attributes = True

# --- User Schemas ---
class UserBase(BaseModel):
    email: EmailStr

class UserCreate(UserBase):
    password: str

class User(UserBase):
    id: int
    is_admin: bool
    subscription_expiry: Optional[datetime.datetime] = None
    simulations: list[Simulation] = []
    materials: list[Material] = []
    tools: list[Tool] = []

    class Config:
        from_attributes = True

# --- Admin Schemas ---
class AdminUserCreate(BaseModel):
    email: EmailStr
    password: str
    is_admin: Optional[bool] = False
    subscription_days: Optional[int] = 30

class AdminUserUpdate(BaseModel):
    subscription_expiry: Optional[datetime.datetime] = None
    is_admin: Optional[bool] = None

class AdminUserPasswordReset(BaseModel):
    new_password: str

# --- NEW: Access Request Schemas ---
class AccessRequestCreate(BaseModel):
    email: EmailStr
    name: str
    company: str

class AccessRequest(AccessRequestCreate):
    id: int
    status: str
    request_date: datetime.datetime

    class Config:
        from_attributes = True
# -----------------------------------
