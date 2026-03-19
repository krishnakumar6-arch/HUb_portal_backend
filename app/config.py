from pydantic_settings import BaseSettings
from typing import List

class Settings(BaseSettings):
    DATABASE_URL: str
    SYNC_DATABASE_URL: str
    REDIS_URL: str = "redis://localhost:6379"
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 480
    GOOGLE_SERVICE_ACCOUNT_JSON: str = ""
    GOOGLE_DRIVE_FILE_ID: str = ""
    APP_ENV: str = "development"
    CORS_ORIGINS: str = "http://localhost:5173"
    ETL_CRON_HOUR: int = 2
    ETL_CRON_MINUTE: int = 0
    ETL_CRON_TIMEZONE: str = "Asia/Kolkata"

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",")]

    class Config:
        env_file = ".env"

settings = Settings()
