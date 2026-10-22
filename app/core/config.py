"""
app/core/config.py
Application settings loaded from environment / .env file.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Security
    secret_key: str = "dev-secret-key-change-in-production"
    access_token_expire_minutes: int = 480

    # Database
    sqlite_db_path: str = "./data/sqlite/autosar_hld.db"

    # Vector DB
    chroma_persist_dir: str = "./data/chroma"

    # LLM
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3"
    ollama_timeout: int = 120
    llm_provider: str = "ollama"

    # Embeddings
    embedding_model: str = "BAAI/bge-base-en-v1.5"
    embedding_device: str = "cpu"
    embedding_batch_size: int = 32

    # Ingestion
    max_upload_mb: int = 100
    chunk_size_tokens: int = 400
    chunk_overlap_tokens: int = 80
    ocr_dpi: int = 300
    tesseract_cmd: str = "tesseract"

    # RAG
    retrieval_top_k: int = 6
    min_confidence_auto_approve: float = 0.8
    low_confidence_threshold: float = 0.6

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # UI
    api_base_url: str = "http://localhost:8000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
