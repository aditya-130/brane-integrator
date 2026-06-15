from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Required ──────────────────────────────────────────────────────────────
    BRANE_INTEGRATOR_API_KEY: str

    # ── BraneHub integration ──────────────────────────────────────────────────
    # Leave empty to run in offline/mock mode (uses app/mockdata/ JSON files)
    BRANEHUB_BASE_URL: str = ""

    # ── LLM ──────────────────────────────────────────────────────────────────
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o"

    # ── Workflow generation ───────────────────────────────────────────────────
    # "map_reduce" = deterministic TemplateGenerator (default, no LLM calls)
    # "llm"        = LlmGenerator (requires OPENAI_API_KEY)
    WORKFLOW_GENERATION_STRATEGY: str = "map_reduce"

    # ── Brane API ─────────────────────────────────────────────────────────────
    BRANE_API_URL: str = "localhost:50051"
    EXECUTION_TIMEOUT_SECONDS: int = 600

    # ── Brane filesystem layout ───────────────────────────────────────────────
    # Leave empty to use the default: ~/brane/<subdir>
    BRANE_NODES_DIR: str = ""      # default: ~/brane/nodes
    BRANE_DATA_DIR: str = ""       # default: ~/brane/data
    BRANE_RESULTS_DIR: str = ""    # default: ~/brane/results
    BRANE_PACKAGES_DIR: str = ""   # default: ~/brane/packages (package build working dirs)

    # Template node: certs, proxy.yml, backend.yml are copied from this node
    # when provisioning new participant/coordinator nodes.
    BRANE_TEMPLATE_NODE: str = "worker1"

    # Path to branelet binary used by "brane package build --init <path>".
    # Set this to bin/branelet (relative to the repo root) or an absolute path.
    # Leave empty to let Brane use its own bundled branelet.
    BRANELET_PATH: str = ""

    # Docker container name for brane-api (used to fix packages dir ownership)
    BRANE_API_CONTAINER: str = "brane-api"

    # Host path to central packages dir (used to fix bind-mount ownership before push).
    # Leave empty to derive automatically from BRANE_NODES_DIR.
    BRANE_CENTRAL_PACKAGES_PATH: str = ""

    # ── WSL2 mode ────────────────────────────────────────────────────────────
    # Set to true when running on WSL2 with Docker Desktop.
    # Enables: brane-fwd socat bridge, /etc/hosts patching, Docker Desktop PATH extension,
    # and automatic restart of central Brane containers after Docker Desktop restarts.
    # On native Linux leave this false — branectl manages Brane containers directly.
    WSL2_MODE: bool = False

    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: str = "sqlite:///./integrator.db"
    SQL_ECHO: bool = False

    # ── Derived paths (computed properties, not env vars) ─────────────────────

    @property
    def brane_nodes_dir(self) -> Path:
        return Path(self.BRANE_NODES_DIR) if self.BRANE_NODES_DIR else Path.home() / "brane" / "nodes"

    @property
    def brane_data_dir(self) -> Path:
        return Path(self.BRANE_DATA_DIR) if self.BRANE_DATA_DIR else Path.home() / "brane" / "data"

    @property
    def brane_results_dir(self) -> Path:
        return Path(self.BRANE_RESULTS_DIR) if self.BRANE_RESULTS_DIR else Path.home() / "brane" / "results"

    @property
    def brane_packages_dir(self) -> Path:
        return Path(self.BRANE_PACKAGES_DIR) if self.BRANE_PACKAGES_DIR else Path.home() / "brane" / "packages"

    @property
    def brane_central_packages_path_resolved(self) -> str:
        if self.BRANE_CENTRAL_PACKAGES_PATH:
            return self.BRANE_CENTRAL_PACKAGES_PATH
        return str(self.brane_nodes_dir / "central" / "packages")

    model_config = {"env_file": ".env"}


settings = Settings()
