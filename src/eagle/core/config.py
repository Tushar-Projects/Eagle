from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Storage
    DATABASE_PATH: str = "sqlite:///./eagle.db"
    CHROMADB_PATH: str = "./chroma_data"

    # AI Provider / Model Configuration
    MODEL_PROVIDER: str = "openai"
    MODEL_BASE_URL: str = "https://api.openai.com/v1"
    MODEL_API_KEY: str = ""
    MODEL_NAME: str = "gpt-4o"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
