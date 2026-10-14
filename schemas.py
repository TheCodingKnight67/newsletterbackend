from pydantic import BaseModel, EmailStr, Field, model_validator, field_validator
from typing import Optional, Literal
import re


class UserSubscribe(BaseModel):
    email: EmailStr
    character_name: str = Field(min_length=1, max_length=120)
    character_series: str = Field(min_length=1, max_length=120)
    message_type: Literal['uplift', 'motivational', 'checkins', 'funny', 'mentalhealth']
    frequency: Literal['daily', 'weekly', 'monthly']
    daily_time: Optional[Literal['morning', 'bedtime', 'both', '']] = None
    notes: Optional[str] = Field(default=None, max_length=2000)

    @field_validator('character_name', 'character_series')
    @classmethod
    def clean_identity(cls, value):
        value = ' '.join(value.split())
        if not value:
            raise ValueError('Character and franchise are required')
        return value

    @model_validator(mode='after')
    def validate_schedule(self):
        if self.frequency == 'daily' and not self.daily_time:
            raise ValueError('Choose a time for daily emails')
        return self


class UserResponse(BaseModel):
    id: int
    email: str
    character_name: str
    confirmed: bool

    class Config:
        from_attributes = True


class CharacterEmailRequest(BaseModel):
    email: EmailStr
    character_name: str = Field(min_length=1, max_length=120)
    character_series: str = Field(min_length=1, max_length=120)
    message_type: Literal['uplift', 'motivational', 'checkins', 'funny', 'mentalhealth'] = 'uplift'
    notes: str = Field(default='', max_length=2000)
    preview: bool = True
    purpose: Literal['regular', 'automation_update'] = 'regular'



    _clean_identity = field_validator('character_name', 'character_series')(UserSubscribe.clean_identity.__func__)


class ProfileImport(BaseModel):
    character_name: str = Field(min_length=1, max_length=120)
    character_series: str = Field(min_length=1, max_length=120)
    markdown: str = Field(min_length=50, max_length=16000)

    _clean_identity = field_validator('character_name', 'character_series')(UserSubscribe.clean_identity.__func__)


class JournalRequest(BaseModel):
    email: EmailStr
    journalEntry: str = Field(min_length=1, max_length=10000)
    style: Literal['plain', 'medieval', 'angelic', 'cozy', 'cozy-pink', 'night-cozy', 'aggressive', 'sad', 'super-happy', 'custom']
    customBackground: Optional[str] = Field(default=None, max_length=2000000)

    @field_validator('customBackground')
    @classmethod
    def validate_image(cls, value):
        if value and not re.fullmatch(r'data:image/(png|jpeg|webp);base64,[A-Za-z0-9+/=\r\n]+', value):
            raise ValueError('Custom backgrounds must be PNG, JPEG or WebP data URLs')
        return value

    @model_validator(mode='after')
    def require_image(self):
        if self.style == 'custom' and not self.customBackground:
            raise ValueError('Custom style requires a background image')
        return self
