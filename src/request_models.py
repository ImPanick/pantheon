# SPDX-License-Identifier: AGPL-3.0-or-later
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List


# Request Models
class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=50000, description="Chat message")
    session: str = Field(..., description="Session ID")
    attachments: Optional[List[str]] = Field(default=[], description="Attachment IDs")
    use_web: Optional[bool] = Field(default=False, description="Enable web search")
    use_research: Optional[bool] = Field(default=False, description="Enable deep research")
    time_filter: Optional[str] = Field(default=None, description="Time filter for search")
    preset_id: Optional[str] = Field(default=None, description="Preset identifier")
    selected_endpoint_id: Optional[str] = Field(default=None, description="Selected model endpoint ID")
    
    @field_validator('message')
    @classmethod
    def clean_message(cls, v):
        return v.strip()
    
    @field_validator('time_filter')
    @classmethod
    def validate_time_filter(cls, v):
        if v is not None and v not in ['day', 'week', 'month', 'year']:
            return None  # Just set to None if invalid rather than raising error
        return v


class MemoryAddRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000, description="Memory text")
    category: str = Field(default="fact", description="Memory category")
    source: str = Field(default="user", description="Memory source")
    session_id: Optional[str] = Field(default=None, description="Associated session ID")

    @field_validator('category')
    @classmethod
    def validate_category(cls, v):
        if v not in ['fact', 'contact', 'task', 'preference', 'identity', 'project', 'goal']:
            return 'fact'  # Default to 'fact' if invalid
        return v


class PresetUpdateRequest(BaseModel):
    """Request model for updating custom preset configuration."""
    name: str = Field(
        "",
        max_length=50,
        description="Character display name (shown next to model name)"
    )
    enabled: bool = Field(
        True,
        description="Whether this character is active"
    )
    temperature: float = Field(
        1.0,
        ge=0.0,
        le=2.0,
        description="Temperature parameter for text generation (0.0-2.0)"
    )
    max_tokens: int = Field(
        0,
        ge=0,
        le=8192,
        description="Maximum number of tokens to generate (0 = no limit)"
    )
    system_prompt: str = Field(
        "",
        max_length=10000,
        description="System prompt to guide assistant behavior (empty = default)"
    )
    inject_prefix: str = Field(
        "",
        max_length=5000,
        description="Text to prepend to each outgoing user message"
    )
    inject_suffix: str = Field(
        "",
        max_length=5000,
        description="Text to append to each outgoing user message"
    )


class DirectoryRequest(BaseModel):
    """Request model for directory operations."""
    directory: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Path to the directory"
    )


class SessionResponse(BaseModel):
    id: str = Field(..., description="Session ID")
    name: str = Field(..., description="Session name")
    model: str = Field(..., description="Model being used")
    rag: bool = Field(default=False, description="RAG enabled")
    archived: bool = Field(default=False, description="Whether session is archived")


