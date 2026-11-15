from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./data/app.db"
    mock_database_url: str = "sqlite:///./data/mock.db"
    checkpoint_url: str = "sqlite:///./data/checkpoints.db"
    app_secret: str = ""
    demo_password: str = ""
    demo_mode: bool = True
    session_seconds: int = 1800
    approval_seconds: int = 900
    provider_mode: str = "fixture"
    openai_api_key: str = ""
    text_model: str = "gpt-4.1-mini"
    vision_model: str = "gpt-4.1-mini"
    embedding_model: str = "text-embedding-3-small"
    stt_model: str = "gpt-4o-mini-transcribe"
    tts_model: str = "gpt-4o-mini-tts"
    judge_model: str = "gpt-4.1-mini"
    model_input_usd_per_million: float = 0
    model_output_usd_per_million: float = 0
    pricing_version: str = "operator-unconfigured"
    embedding_usd_per_million: float = 0
    speech_usd_per_minute: float = 0
    tts_usd_per_million_characters: float = 0
    live_total_budget_usd: float = 0
    live_call_reservation_usd: float = 0
    metering_database_url: str = ""
    mock_url: str = "http://127.0.0.1:8001"
    mcp_url: str = "http://127.0.0.1:8002/mcp"
    mcp_port: int = 8002
    otel_exporter_otlp_endpoint: str = ""
    trace_viewer_url: str = "http://localhost:16686"
    data_dir: Path = Path("data")
    queue_lease_seconds: int = 15
    max_attempts: int = 3
    max_tool_calls: int = 24
    workflow_timeout_seconds: int = 1800
    retention_days: int = 30
    alert_stall_seconds: int = 120
    alert_failure_count: int = 3
    alert_cost_usd: float = 1
    allow_fault_injection: bool = True

    def validate_runtime(self):
        if len(self.app_secret) < 32 or self.app_secret.startswith("replace-"):
            raise RuntimeError("Set a random APP_SECRET (32+ characters); run scripts/setup.py")
        if self.demo_mode and (len(self.demo_password) < 10 or self.demo_password.startswith("replace-")):
            raise RuntimeError("Set DEMO_PASSWORD (10+ characters); run scripts/setup.py")
        if self.provider_mode not in {"fixture", "live"}:
            raise RuntimeError("PROVIDER_MODE must be fixture or live")
        if self.provider_mode == "live" and not self.openai_api_key:
            raise RuntimeError("Live mode requires OPENAI_API_KEY")


@lru_cache
def settings():
    return Settings()
