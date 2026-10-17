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
        # A blank `KEY=` in .env (or docker-compose's `${KEY:-}`) means "use the
        # default" instead of failing to parse "" as a number.
        env_ignore_empty=True,
    )

    output_dir: Path
    temp_dir: Path
    downloads_dir: Path
    # Display only: DOWNLOADS_DIR as the host sees it (the container mounts it
    # at /data/downloads), so the menu can say where to put the session files.
    host_downloads_dir: str = ""

    discord_mapping_file: Path
    whisper_prompt_file: Path
    summary_prompt_file: Path
    quotes_prompt_file: Path
    template_file: Path
    context_dir: Path

    style_rules_file: Path = Path("./prompts/style_rules.txt")
    anti_hallucination_file: Path = Path("./prompts/anti_hallucination.txt")
    validation_prompt_file: Path = Path("./prompts/validation.txt")
    phonetic_corrections_file: Path = Path(
        "../OotD/.agents/skills/rpg-summarizer/resources/phonetic_corrections.md"
    )

    # Session screenshots (Plan E). Unset/empty SCREENSHOTS_DIR disables the
    # feature entirely — the pipeline then runs exactly as before.
    screenshots_dir: str | None = None
    visual_caption_model: str | None = None  # defaults to `gemini_flash_model`
    visual_dedupe: bool = True
    visual_caption_prompt_file: Path = Path("./prompts/visual_caption.txt")
    # Frames are downscaled to this long-edge size and re-encoded as JPEG for
    # the caption upload only (originals on disk stay full-res PNG). 0 = send
    # originals uncompressed.
    visual_upload_max_dim: int = 1536
    visual_upload_jpeg_quality: int = 80
    # ImageMagick crop geometry ("WxH+X+Y") applied to frames before the AI
    # upload AND before the dedupe signature — cuts system/browser chrome
    # (dock, tabs, clock) out of what the caption model sees. Empty = off.
    # Disk originals are never modified.
    visual_crop: str = ""

    # How many trailing `## Sesja N` sections of Timeline.md to include in the
    # campaign context sent to the summarizer (0 = whole file).
    timeline_recent_sessions: int = 10

    summary_chunk_lines: int = 800
    # None = the model's default temperature. Google recommends leaving Gemini
    # 3+ models at their default; lower values can cause looping.
    summary_temperature: float | None = None
    # Off by default: the OotD refine pass rewrites the prose anyway, and a
    # full-draft rewrite is the most output-heavy (expensive) call.
    summary_polish_pass: bool = False
    summary_polish_temperature: float | None = None

    whisper_model: str = "large-v3"
    whisper_device: str = "cuda"
    whisper_compute_type: str = "float16"
    whisper_cache_dir: Path = Path("./models")
    whisper_language: str = "pl"
    whisper_vad: bool = True
    # Names linked in the last N Timeline.md sessions are appended to the
    # hotwords from `whisper_prompt_file` (0 = file only).
    whisper_hotwords_recent_sessions: int = 3

    gemini_api_key: str | None = None
    gemini_pro_model: str = "gemini-4-argon"
    gemini_flash_model: str = "gemini-3.8-flash"
    # Thinking level for the summary, polish and validation calls on the pro
    # model ("low" | "medium" | "high"; None = model default, medium on
    # gemini-4-argon). Thinking tokens are billed as output.
    gemini_thinking_level: str | None = None
    # "flex" = half-price tier with queueing (minutes per call), falling back
    # to "standard" when Flex is at capacity. The pipeline is unattended.
    gemini_service_tier: str = "flex"
    # Validate → auto-fix rounds. A second round only re-checks the draft after
    # simple string replacements, at the cost of another full-transcript call.
    validation_max_passes: int = 1
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
    def foundry_snapshots_dir(self) -> Path:
        """Map snapshots unpacked from a Foundry recorder export."""
        return self.temp_dir / "foundry_snapshots"

    @cached_property
    def processed_dir(self) -> Path:
        return self.downloads_dir / "_processed"

    @cached_property
    def resolved_screenshots_dir(self) -> Path | None:
        """`screenshots_dir` as a concrete path, or None when the feature is off."""
        if self.screenshots_dir is None or not self.screenshots_dir.strip():
            return None
        return Path(self.screenshots_dir)

    @cached_property
    def resolved_visual_caption_model(self) -> str:
        return (self.visual_caption_model or "").strip() or self.gemini_flash_model

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
