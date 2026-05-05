from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    BRANE_INTEGRATOR_API_KEY: str
    BRANEHUB_BASE_URL: str = ""
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"

    model_config = {"env_file": ".env"}


settings = Settings()
