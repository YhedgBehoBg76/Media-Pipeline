from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    RABBITMQ_URL: str
    S3_ENDPOINT: str
    S3_ACCESS_KEY: str
    S3_SECRET_KEY: str
    S3_BUCKET: str

    class Config:
        env_file = ".env"


settings = Settings()