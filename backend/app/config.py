"""读取 .env，给整个 app 用。"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "mysql+pymysql://root:password@localhost:3306/interview_assistant"
    jwt_secret: str = "dev-only-do-not-use-in-prod"
    jwt_expire_days: int = 7
    trongrid_api_key: str = ""
    env: str = "local"
    cors_origins: str = "http://localhost:5173,http://localhost:5174"
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
