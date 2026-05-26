from __future__ import annotations

from functools import cached_property
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    output_dir: Path
    temp_dir: Path
    downloads_dir: Path

    discord_mapping_file: Path
    whisper_prompt_file: Path
    summary_prompt_file: Path
    details_prompt_file: Path
    quotes_prompt_file: Path
    template_file: Path
    context_dir: Path

    whisper_model: str = "large-v3"
    whisper_device: str = "cuda"
    whisper_compute_type: str = "float16"
    whisper_cache_dir: Path = Path("./models")
    whisper_language: str = "pl"
    whisper_vad: bool = True

    gemini_api_key: str | None = None
    gemini_pro_model: str = "gemini-3.1-pro-preview"
    gemini_flash_model: str = "gemini-3-flash-preview"
    gemini_api_sleep_secs: float = 3.0

    log_file: Path = Path("session_processor.log")

    @cached_property
    def sessions_recap_dir(self) -> Path:
        return self.output_dir / "01-Sessions"

    @cached_property
    def assets_base_dir(self) -> Path:
        return self.output_dir / "assets" / "sessions"

    @cached_property
    def audio_output_dir(self) -> Path:
        return self.temp_dir / "audio"

    @cached_property
    def temp_transcriptions_dir(self) -> Path:
        return self.temp_dir / "transcriptions"

    @cached_property
    def processed_dir(self) -> Path:
        return self.downloads_dir / "_processed"

    def ensure_directories(self) -> None:
        for directory in (
            self.output_dir,
            self.temp_dir,
            self.sessions_recap_dir,
            self.assets_base_dir,
            self.audio_output_dir,
            self.temp_transcriptions_dir,
            self.context_dir,
            self.processed_dir,
            self.whisper_cache_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
