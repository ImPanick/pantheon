# SPDX-License-Identifier: AGPL-3.0-or-later
import os
from pathlib import Path
from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator

from src.constants import DATA_DIR as _DATA_DIR_CONST
from src.runtime_paths import get_app_root

# Cross-platform OS flag, exposed here so callers can `from src.config import
# IS_WINDOWS`. Defined locally (a trivial `os.name == "nt"`) rather than imported
# from core.platform_compat, to keep this dependency-light config module from
# dragging in the whole core/__init__ + llm_core import chain. The platform
# *helper functions* (safe_chmod, pid_alive, find_bash, ...) live solely in
# core.platform_compat — that remains their single source of truth. Keep platform
# branches as small inline `if IS_WINDOWS:` deltas (never parallel *_windows.py
# files) so they stay easy to integrate with upstream changes.
IS_WINDOWS = os.name == "nt"

class DataConfig(BaseSettings):
    """Configuration for data storage and file handling."""
    # Base directory
    base_dir: Path = Field(default=Path(get_app_root()), description="Base directory for the application")
    
    # Data paths
    data_dir: Path = Field(default=Path(_DATA_DIR_CONST), description="Main data directory")
    uploads_dir: Path = Field(default=Path(_DATA_DIR_CONST) / "uploads", description="Directory for uploaded files")
    sessions_file: Path = Field(default=Path(_DATA_DIR_CONST) / "sessions.json", description="Sessions storage file")
    memory_file: Path = Field(default=Path(_DATA_DIR_CONST) / "memory.json", description="Memory storage file")
    personal_dir: Path = Field(default=Path(_DATA_DIR_CONST) / "personal_docs", description="Personal documents directory")
    runbook_dir: Path = Field(default=Path(_DATA_DIR_CONST) / "personal_docs" / "runbook", description="Runbook directory")
    
    # Upload settings
    # NOTE (P2-03): an `allowed_extensions` upload allowlist used to live here and
    # was duplicated as a literal inside AppConfig.set_data_paths below. Nothing
    # ever read either copy — the live upload path is UploadHandler.save_upload,
    # which never sees this object. Both copies were deleted rather than wired up:
    # the real enforcement points are src/upload_limits.py (byte caps) and the
    # write-time allowlist on the font upload path (P2-24). Do not re-add a
    # zero-reader allowlist here; it reads as a control while enforcing nothing.
    max_upload_size: int = Field(default=10 * 1024 * 1024, description="Maximum upload size in bytes (10MB)")
    chunk_size: int = Field(default=1000, description="Chunk size for document processing")
    chunk_overlap: int = Field(default=200, description="Overlap between chunks for document processing")
    cleanup_days: int = Field(default=30, description="Number of days after which to clean up old uploads")
    
    model_config = SettingsConfigDict(env_prefix="DATA_")

class LLMConfig(BaseSettings):
    """Configuration for LLM integration."""
    
    # LLM endpoints
    default_host: str = Field(default="localhost", description="Default host for LLM services")
    openai_api_key: Optional[str] = Field(default=None, description="OpenAI API key if using OpenAI")
    openai_compat_path: str = Field(default="/v1/chat/completions", description="OpenAI compatible API path")
    
    # LLM behavior
    max_context_messages: int = Field(default=90, description="Maximum number of context messages to keep")
    request_timeout: int = Field(default=20, description="Request timeout in seconds")
    llm_stream_timeout: int = Field(default=30, description="LLM streaming timeout in seconds")
    llm_max_tokens: int = Field(default=4096, description="Maximum tokens for LLM responses")
    llm_temperature: float = Field(default=0.3, description="Temperature for LLM responses")
    
    model_config = SettingsConfigDict(env_prefix="LLM_")

class SearchConfig(BaseSettings):
    """Configuration for search functionality."""
    
    # Web search
    searxng_instance: str = Field(
        default="http://localhost:8080",
        description="SearXNG instance URL (self-hosted)"
    )
    web_search_count: int = Field(default=10, description="Number of search results to retrieve")
    web_search_max_pages: int = Field(default=6, description="Maximum number of pages to search")
    web_search_max_workers: int = Field(default=4, description="Maximum number of worker threads for web search")
    
    # Research service
    research_service_url: str = Field(
        default="http://localhost:8003/research", 
        description="URL for research service"
    )
    research_timeout: int = Field(default=300, description="Research service timeout in seconds")
    
    # API keys (optional)
    serpapi_key: Optional[str] = Field(default=None, description="SerpAPI key if used")
    google_api_key: Optional[str] = Field(default=None, description="Google API key if used")
    google_cx: Optional[str] = Field(default=None, description="Google Custom Search Engine ID if used")
    
    model_config = SettingsConfigDict(env_prefix="SEARCH_")

class SecurityConfig(BaseSettings):
    """Configuration for security and rate limiting."""
    
    # Rate limiting
    #
    # NOTE (`P12-05b`/`P12-06`, 2026-09-18): **nothing reads any field of this
    # class.** Scope, so the claim can be re-driven: `SecurityConfig` is
    # instantiated once, at `AppConfig.security` below, and `grep -rn
    # "\.security\."` over non-test Python returns that line and nothing else.
    # All six fields here (four rate-limit, `allowed_origins`, `max_file_size`)
    # are declaration without a reader, and `SECURITY_UPLOAD_RATE_LIMIT` in an
    # operator's environment populates a field no code consults. `app.py`
    # imports `config` and passes it to `setup_search_routes`, which never reads
    # it. This is the third time the class has been read as configuration and
    # found to be decoration — see the `P2-03` note below, which deleted nine
    # MIME types and fourteen extensions from it for the same reason.
    #
    # Two of the six were also already wrong, and both were reconciled rather
    # than left to disagree:
    #
    #   * `upload_rate_limit` was **5** here while `UploadHandler.__init__` set
    #     **60**. It is now 60 in both, because 60 is the only one of them that
    #     has ever run: 5 was an unreachable declaration, and picking it would
    #     have cut the chat composer's multi-file attach from 25 files to 5
    #     (issue #1346, "5 work, 6 fail"). The number's home is
    #     `src/upload_handler.py`, where it is enforced; this is a mirror, and
    #     `tests/test_limits_are_policy.py` holds the two equal so they cannot
    #     drift apart again. The live value resolves through
    #     `UploadHandler.effective_upload_rate_limit` — role profile → instance
    #     setting → this floor.
    #   * `max_concurrent_uploads` is 3 in both places and names a concurrency
    #     the upload gate has never measured; the live number is
    #     `upload_burst_limit` in `src/upload_limits.py`, resolved per request
    #     (`P12-06`).
    #
    # `Law 1`: the fields stay and `SECURITY_*` keeps binding to them exactly as
    # pydantic always has. They are labelled so the next reader does not change
    # a value here and wait for something to happen. `B562`.
    max_concurrent_uploads: int = Field(default=3, description="Maximum concurrent uploads per IP")
    upload_rate_limit: int = Field(default=60, description="Maximum uploads per rate window per IP (mirrors UploadHandler)")
    upload_rate_window: int = Field(default=60, description="Rate limit window in seconds")
    upload_rate_max_entries: int = Field(default=1000, description="Maximum number of rate limit entries to keep")
    
    # Security settings
    allowed_origins: List[str] = Field(default=["*"], description="Allowed origins for CORS")
    max_file_size: int = Field(default=10 * 1024 * 1024, description="Maximum file size in bytes")
    # NOTE (P2-03): `dangerous_file_types` (9 MIME types) and `dangerous_extensions`
    # (14 extensions, incl. .sh/.bash/.js/.py) used to live here. Neither was ever
    # read: no module imports this class's fields, so these were a decorative copy
    # of the blocklists that really lived in UploadHandler.is_safe_file_type — which
    # P2-01/D-2026-08-26-01 removed on its own evidence. Deleting a zero-reader copy
    # lifts no control. If the reopen conditions in D-2026-08-26-01 are ever met, the
    # check comes back at the upload path where it can actually run, not here.

    model_config = SettingsConfigDict(env_prefix="SECURITY_")

class AppConfig(BaseSettings):
    """Main application configuration combining all components."""
    
    data: DataConfig = DataConfig()
    llm: LLMConfig = LLMConfig()
    search: SearchConfig = SearchConfig()
    security: SecurityConfig = SecurityConfig()
    
    # Application settings
    debug: bool = Field(default=False, description="Enable debug mode")
    log_level: str = Field(default="INFO", description="Logging level")
    
    @field_validator("data", mode="before")
    def set_data_paths(cls, v, info):
        """Set data paths relative to base_dir."""
        # Get the base_dir from the field values or use default
        if isinstance(v, dict) and "base_dir" in v:
            base_dir = v["base_dir"]
        else:
            base_dir = Path(get_app_root())
        
        # Convert string paths to Path objects relative to base_dir
        data_dir = Path(_DATA_DIR_CONST)
        
        # Get values from the input dict or use defaults
        max_upload_size = v.get("max_upload_size", 10 * 1024 * 1024) if isinstance(v, dict) else 10 * 1024 * 1024
        chunk_size = v.get("chunk_size", 1000) if isinstance(v, dict) else 1000
        chunk_overlap = v.get("chunk_overlap", 200) if isinstance(v, dict) else 200
        cleanup_days = v.get("cleanup_days", 30) if isinstance(v, dict) else 30
        return {
            "base_dir": base_dir,
            "data_dir": data_dir,
            "uploads_dir": data_dir / "uploads",
            "sessions_file": data_dir / "sessions.json",
            "memory_file": data_dir / "memory.json",
            "personal_dir": data_dir / "personal_docs",
            "runbook_dir": data_dir / "personal_docs" / "runbook",
            "max_upload_size": max_upload_size,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "cleanup_days": cleanup_days
        }
    
    model_config = SettingsConfigDict()

# Create global config instance
config = AppConfig()

# Create directories if they don't exist
def create_directories():
    """Create required directories if they don't exist."""
    directories = [
        config.data.data_dir,
        config.data.uploads_dir,
        config.data.personal_dir,
        config.data.runbook_dir
    ]
    
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)

# Validate configuration on startup
def validate_config():
    """Validate the application configuration."""
    # Check if LLM host is reachable if specified
    if config.llm.default_host and config.llm.default_host.startswith("192.168."):
        # This is a local IP, assume it's valid
        pass
    
    # Check if API keys are set when needed
    if not config.llm.openai_api_key:
        # OpenAI API key not set, that's OK if not using OpenAI
        pass
    
    # Create directories
    create_directories()

# Initialize configuration
validate_config()
