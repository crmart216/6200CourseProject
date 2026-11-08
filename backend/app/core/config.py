from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Group Chat API"
    database_url: str = "postgresql+psycopg://chat:chat@localhost:5432/chat"
    server_private_key_path: str = "keys/server_private_key.pem"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
