from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    BRANE_INTEGRATOR_API_KEY: str
    BRANEHUB_BASE_URL: str = ""

    model_config = {"env_file": ".env"}


settings = Settings()
