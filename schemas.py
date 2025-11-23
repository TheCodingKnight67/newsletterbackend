from pydantic import BaseModel, EmailStr
from typing import Optional


class UserSubscribe(BaseModel):
    email: EmailStr
    character_name: str
    character_series: str
    message_type: str
    frequency: str
    daily_time: Optional[str] = None
    notes: Optional[str] = None


class UserResponse(BaseModel):
    id: int
    email: str
    character_name: str
    confirmed: bool

    class Config:
        from_attributes = True