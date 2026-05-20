import asyncio
import logging
import os
import secrets
import subprocess
import time
import httpx
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlmodel import Session, select

from app.api import admin, infra, packages, workflow
from app.domain.workflow import Workflow
from app.infrastructure.database import engine, init_db
from app.infrastructure.settings import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

_WSL_DOCKER_PATH = "/mnt/wsl/docker-desktop/cli-tools/usr/bin"
_CMD_ENV = {**os.environ, "PATH": f"{_WSL_DOCKER_PATH}:{os.environ.get('PATH', '')}"}

# Central containers whose /etc/hosts must point to brane-fwd
_CENTRAL_CONTAINERS = ["brane-api", "brane-drv", "brane-plr", "brane-prx"]


# ── BraneHub helper ────────────────────────────────────────────────────────────

def _cycle_terminal_state(project_id: int) -> Optional[str]:
    try:
        response = httpx.get(
            f"{settings.BRANEHUB_BASE_URL}/api/integration/projects/{project_id}",
            headers={"X-API-Key": settings.BRANE_INTEGRATOR_API_KEY},
            timeout=5,
        )
        if response.status_code == 200:
            return response.json().get("cycle_terminal_state")
    except Exception as e:
        logger.warning("Could not reach BraneHub for project %s: %s", project_id, e)
    return None


# ── Infrastructure management ──────────────────────────────────────────────────

_CENTRAL_DIR = Path.home() / "brane" / "nodes" / "central"

# Per-container run args (image and optional --debug appended at runtime)
_CENTRAL_SPECS: dict[str, list[str]] = {
    "brane-api": [
        "--network", "brane-central", "--restart", "always",
        "--add-host", "host.docker.internal:host-gateway",
        "-p", "0.0.0.0:50051:50051",
        "-v", f"{_CENTRAL_DIR}/node.yml:/node.yml:rw",
        "-v", f"{_CENTRAL_DIR}/infra.yml:{_CENTRAL_DIR}/infra.yml:rw",
        "-v", f"{_CENTRAL_DIR}/certs:{_CENTRAL_DIR}/certs:rw",
        "-v", f"{_CENTRAL_DIR}/packages:{_CENTRAL_DIR}/packages:rw",
    ],
    "brane-drv": [
        "--network", "brane-central", "--restart", "always",
        "--add-host", "host.docker.internal:host-gateway",
        "-p", "0.0.0.0:50053:50053",
        "-v", f"{_CENTRAL_DIR}/node.yml:/node.yml:rw",
        "-v", f"{_CENTRAL_DIR}/infra.yml:{_CENTRAL_DIR}/infra.yml:rw",
    ],
    "brane-plr": [
        "--network", "brane-central", "--restart", "always",
        "--add-host", "host.docker.internal:host-gateway",
        "-v", f"{_CENTRAL_DIR}/node.yml:/node.yml:rw",
        "-v", f"{_CENTRAL_DIR}/infra.yml:{_CENTRAL_DIR}/infra.yml:rw",
    ],
    "brane-prx": [
        "--network", "brane-central", "--restart", "always",
        "--add-host", "host.docker.internal:host-gateway",
        "-v", f"{_CENTRAL_DIR}/node.yml:/node.yml:rw",
        "-v", f"{_CENTRAL_DIR}/proxy.yml:{_CENTRAL_DIR}/proxy.yml:rw",
        "-v", f"{_CENTRAL_DIR}/certs:{_CENTRAL_DIR}/certs:rw",
    ],
}
# plr has no --debug flag; the others do
_CENTRAL_DEBUG = {"brane-api", "brane-drv", "brane-prx"}


def _ensure_central_containers() -> None:
    """
    Recreate any central Brane container that is not running.
    Handles the WSL2 stale bind-mount issue: Docker Desktop restarts
    invalidate bind-mount tokens, causing these containers to exit.
    Image names are read from the existing (exited) containers so no
    version string needs to be hardcoded here.
    """
    any_recreated = False
    for name, run_args in _CENTRAL_SPECS.items():
        running = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Running}}", name],
            capture_output=True, text=True, env=_CMD_ENV,
        ).stdout.strip() == "true"

        if running:
            logger.info("Central container %s is running", name)
            continue

        # Read image from the exited container so we don't hardcode the version
        img = subprocess.run(
            ["docker", "inspect", "--format", "{{.Config.Image}}", name],
            capture_output=True, text=True, env=_CMD_ENV,
        ).stdout.strip()

        if not img:
            logger.warning(
                "Central container %s not found — run 'branectl start central' "
                "once to perform first-time setup", name,
            )
            continue

        logger.info("Central container %s is down — recreating", name)
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, env=_CMD_ENV)
        cmd = ["docker", "run", "-d", "--name", name] + run_args + [img]
        if name in _CENTRAL_DEBUG:
            cmd.append("--debug")
        result = subprocess.run(cmd, capture_output=True, text=True, env=_CMD_ENV)
        if result.returncode == 0:
            logger.info("Recreated central container %s", name)
            any_recreated = True
        else:
            logger.error("Failed to recreate %s: %s", name, result.stderr.strip())

    if any_recreated:
        logger.info("Waiting 5 s for central containers to stabilise...")
        time.sleep(5)


def _check_brane_central() -> bool:
    """Returns True if brane-api is running after _ensure_central_containers()."""
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Running}}", "brane-api"],
        capture_output=True, text=True, env=_CMD_ENV,
    )
    if result.stdout.strip() == "true":
        logger.info("Brane central node (brane-api) is running")
        return True
    logger.critical(
        "brane-api is still not running after recreate attempt. "
        "Run 'branectl start central' once for first-time setup."
    )
    return False


def _rebuild_brane_fwd() -> Optional[str]:
    """
    Destroy and recreate brane-fwd on the brane-central network.
    Returns brane-fwd's IP on brane-central, or None on failure.

    socat rules are NOT added here — reconcile() calls _extend_brane_fwd()
    for each ready DB node after this returns.
    """
    subprocess.run(["docker", "stop", "brane-fwd"], capture_output=True, env=_CMD_ENV)
    subprocess.run(["docker", "rm", "brane-fwd"], capture_output=True, env=_CMD_ENV)

    result = subprocess.run(
        [
            "docker", "run", "-d",
            "--name", "brane-fwd",
            "--network", "brane-central",
            "alpine:latest",
            "/bin/sh", "-c",
            "apk add --no-cache socat > /dev/null 2>&1 && tail -f /dev/null",
        ],
        capture_output=True, text=True, env=_CMD_ENV,
    )
    if result.returncode != 0:
        logger.error("Failed to create brane-fwd container: %s", result.stderr.strip())
        return None

    # Wait for socat to finish installing before any exec calls
    deadline = time.time() + 30
    while time.time() < deadline:
        check = subprocess.run(
            ["docker", "exec", "brane-fwd", "which", "socat"],
            capture_output=True, env=_CMD_ENV,
        )
        if check.returncode == 0:
            break
        time.sleep(1)
    else:
        logger.error("brane-fwd: socat did not install within 30s")
        return None

    # Get brane-fwd's IP on brane-central so central containers can route to it
    fmt = '{{(index .NetworkSettings.Networks "brane-central").IPAddress}}'
    ip_result = subprocess.run(
        ["docker", "inspect", "brane-fwd", "--format", fmt],
        capture_output=True, text=True, env=_CMD_ENV,
    )
    fwd_ip = ip_result.stdout.strip()
    if not fwd_ip:
        logger.error("Could not get brane-fwd IP on brane-central network")
        return None

    logger.info("brane-fwd ready — IP on brane-central: %s", fwd_ip)
    return fwd_ip


def _patch_central_hosts(fwd_ip: str) -> None:
    """
    Rewrite host.docker.internal in each central container's /etc/hosts to
    point to brane-fwd's IP instead of the Windows host (which hits Hyper-V
    port exclusions on WSL2). This lets brane-api/drv/plr/prx reach worker
    nodes through brane-fwd's socat rules.
    """
    patch_cmd = (
        f"grep -v 'host\\.docker\\.internal' /etc/hosts > /tmp/h "
        f"&& printf '{fwd_ip}\\thost.docker.internal\\n' >> /tmp/h "
        f"&& cp /tmp/h /etc/hosts"
    )
    for container in _CENTRAL_CONTAINERS:
        running = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Running}}", container],
            capture_output=True, text=True, env=_CMD_ENV,
        )
        if running.stdout.strip() != "true":
            logger.warning("Central container %s not running — skipping hosts patch", container)
            continue
        result = subprocess.run(
            ["docker", "exec", "-u", "root", container, "sh", "-c", patch_cmd],
            capture_output=True, text=True, env=_CMD_ENV,
        )
        if result.returncode == 0:
            logger.info("Patched host.docker.internal → %s in %s", fwd_ip, container)
        else:
            logger.warning("Hosts patch failed for %s: %s", container, result.stderr.strip())


# ── Startup ────────────────────────────────────────────────────────────────────

def _on_startup() -> None:
    logger.info("Starting Brane Integrator...")
    init_db()

    # 1. Ensure all central Brane containers are running (handles WSL2 stale bind-mounts)
    _ensure_central_containers()
    central_ok = _check_brane_central()

    # 2. Rebuild brane-fwd from scratch and patch central containers
    if central_ok:
        fwd_ip = _rebuild_brane_fwd()
        if fwd_ip:
            _patch_central_hosts(fwd_ip)
        else:
            logger.error("brane-fwd rebuild failed — provisioned nodes will be unreachable")
    else:
        logger.warning("Skipping brane-fwd rebuild — start brane central node and restart the Integrator")

    with Session(engine) as db:
        # 3. Reset stuck workflows
        stuck = db.exec(
            select(Workflow).where(Workflow.status.in_(["generating", "executing"]))
        ).all()
        for w in stuck:
            terminal = _cycle_terminal_state(w.project_id)
            if terminal is not None:
                logger.warning(
                    "Cycle already ended on BraneHub (%s) — marking workflow %s failed",
                    terminal, w.workflow_id,
                )
                w.status = "failed"
            else:
                logger.info(
                    "Cycle still active — resetting workflow %s (%s → pending)",
                    w.workflow_id, w.status,
                )
                w.status = "pending"
            db.add(w)
        db.commit()

        # 4. Reconcile all DB-tracked nodes: restart down containers + re-add socat rules
        from app.application.node_provisioner.node_provisioner import NodeProvisioner
        try:
            NodeProvisioner().reconcile(db)
        except Exception as exc:
            logger.error("Node reconciliation failed: %s", exc)


async def _reconcile_loop() -> None:
    """
    Background task: every 60 s re-extend brane-fwd socat rules for all ready
    nodes. Closes the mid-session gap where brane-fwd can be recreated without
    the Integrator restarting.
    """
    while True:
        await asyncio.sleep(60)
        try:
            with Session(engine) as db:
                from app.application.node_provisioner.node_provisioner import NodeProvisioner
                NodeProvisioner().reconcile(db)
        except Exception as exc:
            logger.error("Background reconcile error: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _on_startup()
    task = asyncio.create_task(_reconcile_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(title="Brane Integrator", lifespan=lifespan)


@app.middleware("http")
async def verify_api_key(request: Request, call_next):
    if request.url.path.startswith("/admin"):
        return await call_next(request)
    provided = request.headers.get("X-API-Key", "")
    if not secrets.compare_digest(settings.BRANE_INTEGRATOR_API_KEY, provided):
        return JSONResponse(
            status_code=401,
            content={"error": "unauthorized", "message": "Missing or invalid X-API-Key"},
        )
    return await call_next(request)


app.include_router(infra.router)
app.include_router(workflow.router)
app.include_router(packages.router)
app.include_router(admin.router)
