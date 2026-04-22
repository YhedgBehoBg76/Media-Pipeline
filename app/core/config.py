from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # === Обязательные поля (используются приложением) ===
    DATABASE_URL: str
    RABBITMQ_URL: str
    S3_ENDPOINT: str
    S3_ACCESS_KEY: str
    S3_SECRET_KEY: str
    S3_BUCKET: str
    SECRET_KEY: str

    # === Опциональные поля со значениями по умолчанию ===
    S3_REGION: str = "us-east-1"
    APP_ENV: str = "development"
    YOUTUBE_API_KEY: str = ""
    GOOGLE_CREDENTIALS_PATH: str = "/app/secrets/credentials.json"
    GOOGLE_TOKEN_PATH: str
    PLATFORMS_CONFIG_PATH: str
    SEGMENTERS_CONFIG_PATH: str

    # === 🔑 КРИТИЧНО: Настройка поведения ===
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # Игнорировать переменные, не объявленные в классе
        case_sensitive=True,  # Учитывать регистр (POSTGRES_USER ≠ postgres_user)
    )


settings = Settings()