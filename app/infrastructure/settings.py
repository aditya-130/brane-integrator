from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    BRANE_INTEGRATOR_API_KEY: str
    BRANEHUB_BASE_URL: str = ""
    BRANE_API_URL: str = "localhost:50051"
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    WORKFLOW_GENERATION_STRATEGY: str = "map_reduce"

    model_config = {"env_file": ".env"}


settings = Settings()
