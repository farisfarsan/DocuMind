from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql://postgres:password@localhost:5432/documind"

    # JWT
    SECRET_KEY: str = "change-this-secret-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # File Storage
    UPLOAD_DIR: str = "./uploads"
    MAX_FILE_SIZE_MB: int = 20

    # Groq
    GROQ_API_KEY: str = ""

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # RabbitMQ (Celery broker)
    RABBITMQ_URL: str = "amqp://guest:guest@localhost:5672//"

    class Config:
        env_file = ".env"


settings = Settings()

Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)