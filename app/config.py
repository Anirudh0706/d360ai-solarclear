"""Runtime configuration. Values come from environment variables (or a local .env file)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """Minimal .env loader so the app has no extra dependency. Real env vars win."""
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


class Settings:
    """Read lazily so tests can override env vars before each use."""

    @property
    def database_path(self) -> str:
        return os.environ.get("DATABASE_PATH", str(BASE_DIR / "solarclear.db"))

    @property
    def secret_key(self) -> str:
        return os.environ.get("SECRET_KEY", "dev-only-change-me")

    @property
    def token_ttl_hours(self) -> float:
        return _float("TOKEN_TTL_HOURS", 12)

    # --- Grid planning limits (tune per state regulation / utility practice) ---
    @property
    def voltage_upper_pu(self) -> float:
        return _float("VOLTAGE_UPPER_PU", 1.06)

    @property
    def reverse_flow_limit_pct(self) -> float:
        return _float("REVERSE_FLOW_LIMIT_PCT", 80)

    @property
    def policy_cap_pct(self) -> float:
        return _float("POLICY_CAP_PCT", 100)

    @property
    def performance_ratio(self) -> float:
        return _float("PV_PERFORMANCE_RATIO", 0.78)

    # --- External services ---
    @property
    def weather_provider(self) -> str:
        return os.environ.get("WEATHER_PROVIDER", "open-meteo").lower()

    @property
    def notify_webhook_url(self) -> str:
        return os.environ.get("NOTIFY_WEBHOOK_URL", "")

    # --- Azure OpenAI (same variable names as the other projects) ---
    @property
    def azure_api_key(self) -> str:
        return os.environ.get("AZURE_OPENAI_API_KEY", "")

    @property
    def azure_endpoint(self) -> str:
        return os.environ.get("AZURE_OPENAI_ENDPOINT", "").rstrip("/")

    @property
    def azure_deployment(self) -> str:
        return os.environ.get("AZURE_OPENAI_DEPLOYMENT", "")

    @property
    def azure_api_version(self) -> str:
        return os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21")

    @property
    def agent_max_tokens(self) -> int:
        return int(_float("AGENT_MAX_COMPLETION_TOKENS", 2500))

    @property
    def agent_reasoning_effort(self) -> str:
        return os.environ.get("AGENT_REASONING_EFFORT", "low")

    @property
    def llm_enabled(self) -> bool:
        return bool(self.azure_api_key and self.azure_endpoint and self.azure_deployment)


settings = Settings()
