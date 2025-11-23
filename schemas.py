from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Any, Dict
import datetime

# --- Tool & Material Schemas ---
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

class MaterialBase(BaseModel):
    name: str
    properties: Any # FIX: Changed from 'str' to 'Any' to handle parsed JSON

class MaterialCreate(MaterialBase):
    pass

class Material(MaterialBase):
    id: int
    owner_id: int
    properties: Any # FIX: Changed from 'str' to 'Any'
    class Config:
        from_attributes = True

# --- NEW R&D SIMULATION PAYLOAD SCHEMAS ---
class SimulationParameters(BaseModel):
    num_steps: int
    time_step_duration_s: float

class SPHParameters(BaseModel):
    smoothing_radius_m: float
    gas_stiffness: float
    viscosity: float

class WorkpieceSetup(BaseModel):
    min_corner: List[float]
    max_corner: List[float]

class MillingParams(BaseModel):
    spindle_speed_rpm: float
    feed_rate_mm_per_rev: float
    tool_axis: List[float]
    feed_direction: List[float]
    ambient_temperature_C: float

class TurningParams(BaseModel):
    sliding_velocity_m_s: float
    strain_rate: float
    ambient_temperature_C: float

class LegacyCFDParams(BaseModel):
    enable_cfd: bool
    rake_angle_degrees: Optional[float] = 0.0

# The Master Request Object
class SimulationRequest(BaseModel):
    name: str
    description: str
    tool_id: int
    material_id: int
    machining_type: str  # 'milling' or 'turning'
    
    simulation_parameters: SimulationParameters
    
    turning_params: Optional[TurningParams] = None
    milling_params: Optional[MillingParams] = None
    legacy_cfd_parameters: Optional[LegacyCFDParams] = None
    sph_parameters: Optional[SPHParameters] = None
    workpiece_setup: Optional[WorkpieceSetup] = None

# --- DB Response Schemas ---
class Simulation(BaseModel):
    id: int
    name: str
    description: str
    status: str
    results: Optional[str] = None
    owner_id: int
    tool_id: Optional[int] = None
    material_id: Optional[int] = None # FIX: Added material_id to response
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

# --- Access Request Schemas ---
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
