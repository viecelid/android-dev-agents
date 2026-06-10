# config/settings.py

from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    """Zentrale Konfiguration für den Entwicklungs-Workflow."""

    # ── LLM API ──
    anthropic_api_key: str
    openai_api_key: str
    openai_api_base: str = "https://openrouter.ai/api/v1"
    openrouter_api_key: str = ""
    default_model: str = "qwen/qwen3.5-397b-a17b"

    # ── GitHub ──
    github_token: str
    github_repo: str
    github_project_number: int
    default_base_branch: str = "developer"

    # ── Projekt-Pfad (einzelnes Repo) ──
    repo_path: str

    # ── Sprache & Extensions ──
    language: str = "kotlin"
    file_extensions: list[str] = [".kt", ".java", ".xml", ".gradle", ".kts"]

    # ── Build ──
    build_command: str = "./gradlew assembleDebug"

    # ── Android App ──
    app_package: str = "ch.ffhs.mosquitobuzz"
    app_name: str = "MosquitoBuzz"
    android_min_sdk: int = 31
    android_target_sdk: int = 35
    android_compile_sdk: int = 36

    # ── Prompts ──
    prompts_dir: str = "prompts"

    # ── Agent-Verhalten ──
    max_retries: int = 3


settings = Settings()
