from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Storage
    DATABASE_PATH: str = "sqlite:///./eagle.db"
    CHROMADB_PATH: str = "./chroma_data"

    # AI Provider — Generic Selection (Reconciliation & Exception Classification)
    AI_PROVIDER: str = "mock"       # "gemini", "claude", "llama_server", "mock"
    AI_MODEL: str = ""              # Provider-specific model name
    LLAMA_SERVER_URL: str = "http://127.0.0.1:8000"

    # Vision Provider — Image & Scanned Document Extraction (Independent from AI_PROVIDER)
    VISION_PROVIDER: str = "llama_server"   # "nvidia_nim", "llama_server", "mock"
    VISION_MODEL: str = "meta/llama-3.2-11b-vision-instruct"
    NVIDIA_NIM_API_KEY: str = ""
    NVIDIA_NIM_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    VISION_TIMEOUT_SECONDS: int = 60

    # Provider-Specific Credentials
    GEMINI_API_KEY: str = ""
    CLAUDE_API_KEY: str = ""

    # Classifier Configuration
    AI_MAX_RETRIES: int = 2
    AI_TIMEOUT_SECONDS: int = 30
    AI_MAX_CONCURRENCY: int = 5     # Bounded parallelism for async

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
