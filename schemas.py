from pydantic import BaseModel
from typing import Optional, Any

# --- Tool Schemas ---
class ToolBase(BaseModel):
    name: str
    tool_type: Optional[str] = None

class ToolCreate(ToolBase):
    pass # file_path will be handled by the server, not the client

class Tool(ToolBase):
    id: int
    file_path: str
    owner_id: int

    class Config:
        orm_mode = True

# --- Material Schemas ---
class MaterialBase(BaseModel):
    name: str
    properties: Any # Will be parsed from a JSON string

class MaterialCreate(MaterialBase):
    pass

class Material(MaterialBase):
    id: int
    owner_id: int
    
    # In the response, properties will be a string.
    # If you parse it in crud, you can change this.
    properties: str 

    class Config:
        orm_mode = True

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
        orm_mode = True

# --- User Schemas ---
class UserBase(BaseModel):
    email: str

class UserCreate(UserBase):
    password: str

class User(UserBase):
    id: int
    # --- THIS LINE WAS REMOVED ---
    # is_active: bool 
    simulations: list[Simulation] = []
    materials: list[Material] = []
    tools: list[Tool] = []

    class Config:
        orm_mode = True
