from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
REPOS_DIR = DATA_DIR / "repos"
CHROMA_DIR = DATA_DIR / "chroma"
DOCS_DIR = DATA_DIR / "docs"
WORKSPACE_FILE = DATA_DIR / "workspace.json"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"

    chatanywhere_api_key: str = ""
    chatanywhere_base_url: str = "https://api.chatanywhere.tech/v1"
    chatanywhere_model: str = "gpt-4o-mini"

    @property
    def effective_api_key(self) -> str:
        return self.openai_api_key.strip() or self.chatanywhere_api_key.strip()

    @property
    def effective_base_url(self) -> str:
        if self.openai_api_key.strip():
            return self.openai_base_url.strip()
        if self.chatanywhere_api_key.strip():
            url = self.chatanywhere_base_url.strip().rstrip("/")
            if url.endswith("/chat"):
                url = url[:-5]
            return url
        return self.openai_base_url.strip()

    @property
    def effective_model(self) -> str:
        if self.openai_api_key.strip() and self.openai_model:
            return self.openai_model.strip()
        if self.chatanywhere_api_key.strip() and self.chatanywhere_model:
            return self.chatanywhere_model.strip()
        return "gpt-4o-mini"


settings = Settings()
REPOS_DIR.mkdir(parents=True, exist_ok=True)
CHROMA_DIR.mkdir(parents=True, exist_ok=True)
DOCS_DIR.mkdir(parents=True, exist_ok=True)
