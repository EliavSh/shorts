from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Force .env values to override empty/preset shell env vars. Without this,
# a shell that exported ANTHROPIC_API_KEY="" silently blocks the .env value.
load_dotenv(override=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM
    anthropic_api_key: str = ""
    claude_model: str = "claude-opus-4-7"          # script writer — quality matters
    claude_director_model: str = "claude-sonnet-4-6"  # visual director — cheap structured JSON
    claude_model_fallback: str = "claude-sonnet-4-6"

    # TTS
    tts_provider: Literal["edge", "elevenlabs"] = "edge"
    edge_voice_en: str = "en-US-AndrewNeural"
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id_en: str = ""

    # Market data
    finnhub_api_key: str = ""
    newsapi_key: str = ""

    # B-roll
    pexels_api_key: str = ""

    # Image retrieval (Phase 6)
    google_cse_api_key: str = ""
    google_cse_id: str = ""
    serper_api_key: str = ""  # serper.dev — drop-in replacement for Google CSE
    image_license_mode: Literal["strict_pd", "mixed", "editorial"] = "editorial"
    visual_cache_dir: Path = Path("./data/stocks/visual_cache")
    clip_model_name: str = "ViT-B-32"  # open_clip checkpoint

    # YouTube
    youtube_client_secrets_path: Path = Path("./secrets/youtube_client_secret.json")
    youtube_token_path: Path = Path("./secrets/youtube_token.json")
    youtube_staging_channel_id: str = ""
    youtube_public_channel_id: str = ""

    # App — paths default to the stocks-isolated data dir.
    db_url: str = "sqlite:///./data/stocks/stocksreels.db"
    data_dir: Path = Path("./data/stocks")
    output_dir: Path = Path("./data/stocks/output")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Dashboard
    dashboard_user: str = "admin"
    dashboard_password: str = "changeme"

    # Local-dev escape hatch: skip TLS verification on outbound HTTPS calls.
    # NEVER set this on the production VPS.
    ssl_no_verify: bool = False

    # Background music
    music_dir: Path = Path("./assets/music")
    music_volume_db: float = -22.0  # how many dB to duck under voice

    # Alerting
    slack_webhook_url: str = ""

    # Project root resolution — settings.py lives at src/shorts/pipelines/stocks/,
    # so 4 levels up is the repo root.
    project_root: Path = Field(default_factory=lambda: Path(__file__).resolve().parents[4])

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.output_dir, self.youtube_token_path.parent, self.visual_cache_dir):
            d.mkdir(parents=True, exist_ok=True)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
