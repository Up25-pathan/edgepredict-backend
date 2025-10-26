from typing import List, Optional, Any
from pydantic import BaseModel

class MaterialBase(BaseModel):
    name: str
    properties: Any
class MaterialCreate(MaterialBase): pass
class Material(MaterialBase):
    id: int
    owner_id: int
    class Config: from_attributes = True

class ToolBase(BaseModel):
    name: str
class ToolCreate(ToolBase): pass
class Tool(ToolBase):
    id: int
    file_path: str
    owner_id: int
    class Config: from_attributes = True

class SimulationBase(BaseModel):
    name: str
    description: Optional[str] = None
class SimulationCreate(SimulationBase): pass
class Simulation(SimulationBase):
    id: int
    owner_id: int
    status: str
    results: Optional[str] = None
    tool_id: Optional[int] = None
    material_properties: Optional[str] = None
    class Config: from_attributes = True

class UserBase(BaseModel):
    email: str
class UserCreate(UserBase):
    password: str
class User(UserBase):
    id: int
    is_active: bool
    simulations: List[Simulation] = []
    materials: List[Material] = []
    tools: List[Tool] = []
    class Config: from_attributes = True
