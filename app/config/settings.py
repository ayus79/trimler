from pydantic_settings import BaseSettings


class SettingsConfig(BaseSettings):
    app_name: str = "Trimler"
    app_version: str = "0.1.0"
    app_env: str = "local"
    api_docs_username: str = "admin@usp"
    api_docs_password: str = "admin@usp"
    api_docs_allowed_ips: str = "127.0.0.1,localhost"
    database_name: str = "trimler"
    redis_url: str = "redis://localhost:6379/0"
    database_url: str = f"postgresql://postgres@localhost:5432/{database_name}"

    class Config:
        env_file = ".env"


settings = SettingsConfig()
