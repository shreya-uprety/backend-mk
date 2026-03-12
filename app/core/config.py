from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_ENV: str = "development"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    APP_TITLE: str = "MedForce Milton Key"
    APP_DESCRIPTION: str = "Agentic nursing assistant for patient record analysis, risk assessment, and consultation support."
    APP_VERSION: str = "0.1.0"
    GOOGLE_API_KEY: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
