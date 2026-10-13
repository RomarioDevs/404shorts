"""Validated application configuration."""

import os
from pathlib import Path

from platformdirs import user_cache_path, user_data_path, user_log_path
from pydantic import BaseModel, ConfigDict, Field


class AppConfig(BaseModel):
    """Runtime settings with safe defaults."""

    model_config = ConfigDict(frozen=True)

    app_name: str = "CortaFlow AI"
    organization: str = "CortaFlow"
    max_concurrent_tasks: int = Field(default=1, ge=1, le=8)
    data_dir: Path = Field(default_factory=lambda: user_data_path("CortaFlowAI", "CortaFlow"))
    cache_dir: Path = Field(default_factory=lambda: user_cache_path("CortaFlowAI", "CortaFlow"))
    log_dir: Path = Field(default_factory=lambda: user_log_path("CortaFlowAI", "CortaFlow"))

    @property
    def whisper_model_cache(self) -> Path:
        """Keep native model paths below Windows' legacy path limit."""
        if os.name == "nt":
            return Path.home() / ".cortaflow" / "model-cache"
        return self.cache_dir / "models" / "faster-whisper"

    @property
    def preview_dir(self) -> Path:
        """Use a short root for video names and native FFmpeg output paths."""
        if os.name == "nt":
            return Path.home() / ".cortaflow" / "previews"
        return self.cache_dir / "previews"

    @property
    def render_temp_dir(self) -> Path:
        """Keep temporary subtitle paths independent of export filenames."""
        if os.name == "nt":
            return Path.home() / ".cortaflow" / "tmp"
        return self.cache_dir / "render-temp"

    def ensure_directories(self) -> None:
        """Create application-owned runtime directories."""
        for path in (self.data_dir, self.cache_dir, self.log_dir):
            path.mkdir(parents=True, exist_ok=True)

