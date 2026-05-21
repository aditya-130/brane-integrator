from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    BRANE_INTEGRATOR_API_KEY: str
    BRANEHUB_BASE_URL: str = ""
    BRANE_API_URL: str = "localhost:50051"
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o"
    WORKFLOW_GENERATION_STRATEGY: str = "map_reduce"
    BRANELET_PATH: str = ""  # path to local branelet binary; if set, passed as --init to brane package build
    BRANE_API_CONTAINER: str = "brane-api"  # Docker container name for brane-api
    BRANE_CENTRAL_PACKAGES_PATH: str = "/home/aditya/brane/nodes/central/packages"  # host path to central packages dir (used to fix bind-mount ownership before push)

    model_config = {"env_file": ".env"}


settings = Settings()
