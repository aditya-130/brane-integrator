import logging
import os
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml
from jinja2 import Environment, FileSystemLoader
from sqlmodel import Session, select

from app.domain.infra import CoordinatorNode, ParticipantNodeMap, ProvisionedNode
from app.domain.package import PackageSource
from app.application.package_manager.package_builder import PackageBuilder
from app.infrastructure.settings import settings

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

_BASE_PORT = 51000
_PORTS_PER_NODE = 5          # reg, job, chk_deliberation, chk_store, prx
_HEALTH_TIMEOUT = 60
_HEALTH_INTERVAL = 2

_TEMPLATE_DIR = Path(__file__).parent.parent.parent / "templates"
_NODE_TEMPLATE_DIR = Path(__file__).parent.parent.parent.parent / "brane-node-template"

# On WSL2, Docker Desktop places its CLI tools at a non-standard path.
# _CMD_ENV extends PATH only when WSL2_MODE is enabled.
_WSL_DOCKER_PATH = "/mnt/wsl/docker-desktop/cli-tools/usr/bin"
_CMD_ENV = (
    {**os.environ, "PATH": f"{_WSL_DOCKER_PATH}:{os.environ.get('PATH', '')}"}
    if settings.WSL2_MODE
    else dict(os.environ)
)


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class PortBlock:
    reg: int
    job: int
    chk_deliberation: int
    chk_store: int
    prx: int


@dataclass
class ProvisionResult:
    brane_node: str
    status: str          # "ready" | "failed"
    error: Optional[str] = None


# ── Private helpers ────────────────────────────────────────────────────────────

def _check_node_running(brane_node: str) -> bool:
    for svc in ("reg", "job", "chk", "prx"):
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Running}}", f"brane-{svc}-{brane_node}"],
            capture_output=True, text=True, env=_CMD_ENV,
        )
        if result.stdout.strip() != "true":
            return False
    return True


def _find_active_node_for_user(user_id: int, db: Session) -> Optional[ProvisionedNode]:
    return db.exec(
        select(ProvisionedNode).where(
            ProvisionedNode.user_id == user_id,
            ProvisionedNode.status == "ready",
        )
    ).first()


def _is_port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("", port))
            return True
        except OSError:
            return False


def _allocate_ports(db: Session) -> PortBlock:
    p_rows = db.exec(select(ProvisionedNode)).all()
    c_rows = db.exec(select(CoordinatorNode)).all()
    all_ports = []
    for n in p_rows:
        all_ports.extend([n.port_reg, n.port_job, n.port_chk_deliberation, n.port_chk_store, n.port_prx])
    for n in c_rows:
        all_ports.extend([n.port_reg, n.port_job, n.port_chk_deliberation, n.port_chk_store, n.port_prx])
    if not all_ports:
        base = _BASE_PORT
    else:
        max_port = max(all_ports)
        used_blocks = (max_port - _BASE_PORT) // _PORTS_PER_NODE + 1
        base = _BASE_PORT + used_blocks * _PORTS_PER_NODE

    for _ in range(200):
        candidate = [base, base + 1, base + 2, base + 3, base + 4]
        if all(_is_port_free(p) for p in candidate):
            return PortBlock(
                reg=base,
                job=base + 1,
                chk_deliberation=base + 2,
                chk_store=base + 3,
                prx=base + 4,
            )
        base += _PORTS_PER_NODE
    raise RuntimeError("Could not find a free port block in range")


def _render_node_yml(working_dir: Path, brane_node: str, ports: PortBlock) -> None:
    env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)))
    tmpl = env.get_template("node.yml.j2")
    rendered = tmpl.render(
        brane_node=brane_node,
        working_dir=str(working_dir),
        data_dir=str(settings.brane_data_dir),
        results_dir=str(settings.brane_results_dir),
        port_reg=ports.reg,
        port_job=ports.job,
        port_chk_deliberation=ports.chk_deliberation,
        port_chk_store=ports.chk_store,
        port_prx=ports.prx,
    )
    (working_dir / "node.yml").write_text(rendered)


def _copy_template_files(working_dir: Path) -> None:
    src = _NODE_TEMPLATE_DIR / "worker-node"
    shutil.copytree(src / "certs", working_dir / "certs", dirs_exist_ok=True)
    for fname in ("proxy.yml", "backend.yml", "policies.db",
                  "policy_delib_secret.json", "policy_store_secret.json"):
        shutil.copy2(src / fname, working_dir / fname)
    (working_dir / "packages").mkdir(exist_ok=True)


def _register_central_cert(brane_node: str) -> None:
    src = _NODE_TEMPLATE_DIR / "central-certs"
    dst = settings.brane_nodes_dir / "central" / "certs" / brane_node
    dst.mkdir(parents=True, exist_ok=True)
    for fname in ("ca.pem", "client-id.pem"):
        shutil.copy2(src / fname, dst / fname)
    logger.info("Registered central cert for %s", brane_node)


def _start_node(working_dir: Path) -> None:
    node_yml = working_dir / "node.yml"
    result = subprocess.run(
        ["branectl", "start", "worker", "--skip-import", "-n", str(node_yml)],
        capture_output=True,
        text=True,
        timeout=120,
        env=_CMD_ENV,
    )
    if result.returncode != 0:
        raise RuntimeError(f"branectl start worker failed: {result.stderr}")
    logger.info("branectl start worker: %s", result.stdout.strip())


def _health_check(host: str, ports: PortBlock) -> None:
    deadline = time.time() + _HEALTH_TIMEOUT
    for port in (ports.reg, ports.job):
        while True:
            try:
                with socket.create_connection((host, port), timeout=2):
                    logger.info("Port %d is up", port)
                    break
            except OSError:
                if time.time() > deadline:
                    raise TimeoutError(f"Port {port} did not come up within {_HEALTH_TIMEOUT}s")
                time.sleep(_HEALTH_INTERVAL)


def _patch_infra_yml(brane_node: str, ports: PortBlock) -> None:
    infra_yml = settings.brane_nodes_dir / "central" / "infra.yml"
    with open(infra_yml) as f:
        infra = yaml.safe_load(f)

    infra.setdefault("locations", {})[brane_node] = {
        "name": brane_node,
        "delegate": f"host.docker.internal:{ports.job}",
        "registry": f"host.docker.internal:{ports.reg}",
    }

    with open(infra_yml, "w") as f:
        yaml.dump(infra, f, default_flow_style=False, allow_unicode=True)
    logger.info("Patched infra.yml with %s", brane_node)


def _get_container_ip(container_name: str, network: str) -> str:
    fmt = '{{index .NetworkSettings.Networks "' + network + '" "IPAddress"}}'
    result = subprocess.run(
        ["docker", "inspect", container_name, "--format", fmt],
        capture_output=True, text=True, env=_CMD_ENV,
    )
    return result.stdout.strip()


def _extend_brane_fwd(brane_node: str, ports: PortBlock) -> None:
    """
    Connect the worker network to brane-fwd and add socat forwarding rules.
    WSL2-specific: on native Linux, Docker networking does not require this bridge.
    Only called when WSL2_MODE=true.
    """
    network = f"brane-worker-{brane_node}"
    subprocess.run(
        ["docker", "network", "connect", network, "brane-fwd"],
        capture_output=True, env=_CMD_ENV,
    )

    reg_ip = _get_container_ip(f"brane-reg-{brane_node}", network)
    job_ip = _get_container_ip(f"brane-job-{brane_node}", network)
    chk_ip = _get_container_ip(f"brane-chk-{brane_node}", network)

    rules = [
        f"socat TCP-LISTEN:{ports.reg},reuseaddr,fork TCP:{reg_ip}:{ports.reg} &",
        f"socat TCP-LISTEN:{ports.job},reuseaddr,fork TCP:{job_ip}:{ports.job} &",
        f"socat TCP-LISTEN:{ports.chk_deliberation},reuseaddr,fork TCP:{chk_ip}:{ports.chk_deliberation} &",
        f"socat TCP-LISTEN:{ports.chk_store},reuseaddr,fork TCP:{chk_ip}:{ports.chk_store} &",
    ]
    for rule in rules:
        subprocess.run(
            ["docker", "exec", "brane-fwd", "sh", "-c", rule],
            capture_output=True, env=_CMD_ENV,
        )
    logger.info("Extended brane-fwd with socat rules for %s", brane_node)


def _get_chk_ports_from_container(brane_node: str) -> tuple[int, int]:
    result = subprocess.run(
        ["docker", "inspect", f"brane-chk-{brane_node}", "--format", "{{json .HostConfig.PortBindings}}"],
        capture_output=True, text=True, env=_CMD_ENV,
    )
    import json as _json
    bindings = _json.loads(result.stdout.strip() or "{}")
    ports = sorted(int(k.split("/")[0]) for k in bindings if bindings[k])
    if len(ports) >= 2:
        return ports[0], ports[1]
    if len(ports) == 1:
        return ports[0], ports[0] + 1
    return 0, 0


def _extend_brane_fwd_static() -> None:
    """
    Re-add socat rules for static nodes (those in infra.yml but not provisioned
    by the Integrator). WSL2-specific — only called when WSL2_MODE=true.
    """
    infra_yml = settings.brane_nodes_dir / "central" / "infra.yml"
    try:
        with open(infra_yml) as f:
            infra = yaml.safe_load(f) or {}
    except Exception as exc:
        logger.warning("_extend_brane_fwd_static: could not read infra.yml: %s", exc)
        return

    managed_prefixes = ("participant-", "coordinator-")
    for location_name, loc in infra.get("locations", {}).items():
        if any(location_name.startswith(p) for p in managed_prefixes):
            continue
        try:
            reg_port = int(loc.get("registry", ":0").split(":")[-1])
            job_port = int(loc.get("delegate", ":0").split(":")[-1])
            chk_delib, chk_store = _get_chk_ports_from_container(location_name)
            if not reg_port or not job_port:
                logger.debug("_extend_brane_fwd_static: no ports found for %s — skipping", location_name)
                continue
            ports = PortBlock(
                reg=reg_port,
                job=job_port,
                chk_deliberation=chk_delib,
                chk_store=chk_store,
                prx=0,
            )
            _extend_brane_fwd(location_name, ports)
        except Exception as exc:
            logger.warning("_extend_brane_fwd_static: failed for %s: %s", location_name, exc)


def _remove_from_infra_yml(brane_node: str) -> None:
    infra_yml = settings.brane_nodes_dir / "central" / "infra.yml"
    with open(infra_yml) as f:
        infra = yaml.safe_load(f)
    infra.get("locations", {}).pop(brane_node, None)
    with open(infra_yml, "w") as f:
        yaml.dump(infra, f, default_flow_style=False, allow_unicode=True)


def _register_dataset(dataset_name: str, file_bytes: bytes | None = None) -> None:
    """
    Register a dataset with Brane's local data index.
    In a real deployment the hospital IT team does this on their own node.
    This simulates the step locally for end-to-end testing.
    """
    data_dir = settings.brane_data_dir / dataset_name
    data_dir.mkdir(parents=True, exist_ok=True)

    if file_bytes is not None:
        (data_dir / "dataset.csv").write_bytes(file_bytes)
        logger.info("Wrote dataset.csv (%d bytes) to %s", len(file_bytes), data_dir)

    csv_path = data_dir / "dataset.csv"
    if not csv_path.exists():
        raise FileNotFoundError(
            f"No dataset.csv found at {csv_path}. Upload a CSV file to register."
        )

    data_yml = data_dir / "data.yml"
    data_yml.write_text(
        f"name: {dataset_name}\n\naccess: !file\n  path: ./dataset.csv\n"
    )
    logger.info("Wrote data.yml for dataset '%s'", dataset_name)

    result = subprocess.run(
        ["brane", "data", "build", str(data_yml)],
        capture_output=True, text=True,
        cwd=str(data_dir),
        env=_CMD_ENV,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"brane data build failed for '{dataset_name}':\n{result.stderr or result.stdout}"
        )
    logger.info("Dataset '%s' registered with Brane", dataset_name)


def _stop_node(brane_node: str) -> None:
    for svc in ("reg", "job", "chk", "prx"):
        container = f"brane-{svc}-{brane_node}"
        subprocess.run(["docker", "stop", container], capture_output=True, env=_CMD_ENV)
        subprocess.run(["docker", "rm", "-f", container], capture_output=True, env=_CMD_ENV)
    subprocess.run(
        ["docker", "network", "rm", f"brane-worker-{brane_node}"],
        capture_output=True, env=_CMD_ENV,
    )


# ── Public API ─────────────────────────────────────────────────────────────────

class NodeProvisioner:

    def provision(self, user_id: int, project_id: int, db: Session) -> ProvisionResult:
        brane_node = f"participant-{user_id}"

        existing = db.exec(
            select(ProvisionedNode).where(
                ProvisionedNode.user_id == user_id,
                ProvisionedNode.project_id == project_id,
                ProvisionedNode.status == "ready",
            )
        ).first()
        if existing:
            logger.info("Node %s already ready for project %d", brane_node, project_id)
            return ProvisionResult(brane_node=brane_node, status="ready")

        in_progress = db.exec(
            select(ProvisionedNode).where(
                ProvisionedNode.user_id == user_id,
                ProvisionedNode.project_id == project_id,
                ProvisionedNode.status == "provisioning",
            )
        ).first()
        if in_progress:
            logger.info("Node %s already provisioning for project %d — ignoring duplicate", brane_node, project_id)
            return ProvisionResult(brane_node=brane_node, status="ready")

        active = _find_active_node_for_user(user_id, db)
        if active:
            logger.info(
                "Reusing existing node %s for project %d (already runs project %d)",
                brane_node, project_id, active.project_id,
            )
            self._push_package(project_id, db)
            row = ProvisionedNode(
                user_id=user_id,
                project_id=project_id,
                brane_node=active.brane_node,
                port_reg=active.port_reg,
                port_job=active.port_job,
                port_chk_deliberation=active.port_chk_deliberation,
                port_chk_store=active.port_chk_store,
                port_prx=active.port_prx,
                working_dir=active.working_dir,
                status="ready",
                provisioned_at=datetime.now(timezone.utc),
            )
            db.add(row)
            db.commit()
            return ProvisionResult(brane_node=brane_node, status="ready")

        try:
            ports = _allocate_ports(db)
            working_dir = settings.brane_nodes_dir / brane_node
            working_dir.mkdir(parents=True, exist_ok=True)

            row = ProvisionedNode(
                user_id=user_id,
                project_id=project_id,
                brane_node=brane_node,
                port_reg=ports.reg,
                port_job=ports.job,
                port_chk_deliberation=ports.chk_deliberation,
                port_chk_store=ports.chk_store,
                port_prx=ports.prx,
                working_dir=str(working_dir),
                status="provisioning",
                provisioned_at=datetime.now(timezone.utc),
            )
            db.add(row)
            db.commit()

            _render_node_yml(working_dir, brane_node, ports)
            _copy_template_files(working_dir)
            _register_central_cert(brane_node)
            _stop_node(brane_node)
            _start_node(working_dir)
            _health_check("localhost", ports)
            _patch_infra_yml(brane_node, ports)
            if settings.WSL2_MODE:
                _extend_brane_fwd(brane_node, ports)
            self._push_package(project_id, db)

            row.status = "ready"
            db.add(row)

            mapping = db.exec(
                select(ParticipantNodeMap).where(ParticipantNodeMap.user_id == user_id)
            ).first()
            if mapping:
                mapping.brane_node = brane_node
            else:
                db.add(ParticipantNodeMap(user_id=user_id, brane_node=brane_node))

            db.commit()
            logger.info("Provisioned %s on ports reg=%d job=%d", brane_node, ports.reg, ports.job)
            return ProvisionResult(brane_node=brane_node, status="ready")

        except Exception as exc:
            logger.error("Provisioning failed for user %d project %d: %s", user_id, project_id, exc)
            try:
                _stop_node(brane_node)
            except Exception:
                pass
            try:
                stale = db.exec(
                    select(ProvisionedNode).where(
                        ProvisionedNode.user_id == user_id,
                        ProvisionedNode.project_id == project_id,
                        ProvisionedNode.status == "provisioning",
                    )
                ).first()
                if stale:
                    db.delete(stale)
                    db.commit()
            except Exception:
                pass
            return ProvisionResult(brane_node=brane_node, status="failed", error=str(exc))

    def deprovision(self, user_id: int, project_id: int, db: Session) -> None:
        row = db.exec(
            select(ProvisionedNode).where(
                ProvisionedNode.user_id == user_id,
                ProvisionedNode.project_id == project_id,
                ProvisionedNode.status == "ready",
            )
        ).first()
        if not row:
            logger.warning("deprovision: no active row for user %d project %d", user_id, project_id)
            return

        brane_node = row.brane_node
        working_dir = Path(row.working_dir)
        logger.info("deprovisioning %s (working_dir=%s)", brane_node, working_dir)

        row.status = "deprovisioned"
        row.deprovisioned_at = datetime.now(timezone.utc)
        db.commit()

        other_active = db.exec(
            select(ProvisionedNode).where(
                ProvisionedNode.user_id == user_id,
                ProvisionedNode.status == "ready",
            )
        ).all()

        if other_active:
            logger.info(
                "Node %s still in use by %d other project(s) — keeping containers up",
                brane_node, len(other_active),
            )
            return

        try:
            _stop_node(brane_node)
            _remove_from_infra_yml(brane_node)
            if working_dir.exists():
                shutil.rmtree(working_dir)

            mapping = db.exec(
                select(ParticipantNodeMap).where(ParticipantNodeMap.user_id == user_id)
            ).first()
            if mapping:
                db.delete(mapping)
            db.commit()
            logger.info("Fully deprovisioned %s", brane_node)
        except Exception as exc:
            logger.error("Teardown error for %s: %s", brane_node, exc)

    def provision_coordinator(self, project_id: int, db: Session) -> ProvisionResult:
        brane_node = f"coordinator-{project_id}"

        existing = db.exec(
            select(CoordinatorNode).where(
                CoordinatorNode.project_id == project_id,
                CoordinatorNode.status == "ready",
            )
        ).first()
        if existing:
            logger.info("Coordinator %s already ready for project %d", brane_node, project_id)
            return ProvisionResult(brane_node=brane_node, status="ready")

        try:
            ports = _allocate_ports(db)
            working_dir = settings.brane_nodes_dir / brane_node
            working_dir.mkdir(parents=True, exist_ok=True)

            row = CoordinatorNode(
                project_id=project_id,
                brane_node=brane_node,
                port_reg=ports.reg,
                port_job=ports.job,
                port_chk_deliberation=ports.chk_deliberation,
                port_chk_store=ports.chk_store,
                port_prx=ports.prx,
                working_dir=str(working_dir),
                status="provisioning",
                provisioned_at=datetime.now(timezone.utc),
            )
            db.add(row)
            db.commit()

            _render_node_yml(working_dir, brane_node, ports)
            _copy_template_files(working_dir)
            _register_central_cert(brane_node)
            _stop_node(brane_node)
            _start_node(working_dir)
            _health_check("localhost", ports)
            _patch_infra_yml(brane_node, ports)
            if settings.WSL2_MODE:
                _extend_brane_fwd(brane_node, ports)
            self._push_package(project_id, db)

            row.status = "ready"
            db.add(row)

            from app.domain.infra import ProjectConfig
            config = db.exec(
                select(ProjectConfig).where(ProjectConfig.project_id == project_id)
            ).first()
            if config:
                config.coordinator_node = brane_node
                db.add(config)
            else:
                src = db.get(PackageSource, project_id)
                if src and src.local_function and src.combine_function:
                    db.add(ProjectConfig(
                        project_id=project_id,
                        coordinator_node=brane_node,
                        package=src.package_name,
                        local_function=src.local_function,
                        combine_function=src.combine_function,
                        finalize_function=src.finalize_function,
                    ))

            db.commit()
            logger.info("Provisioned coordinator %s ports reg=%d job=%d", brane_node, ports.reg, ports.job)
            return ProvisionResult(brane_node=brane_node, status="ready")

        except Exception as exc:
            logger.error("Coordinator provisioning failed for project %d: %s", project_id, exc)
            try:
                stale = db.exec(
                    select(CoordinatorNode).where(
                        CoordinatorNode.project_id == project_id,
                        CoordinatorNode.status == "provisioning",
                    )
                ).first()
                if stale:
                    db.delete(stale)
                    db.commit()
            except Exception:
                pass
            return ProvisionResult(brane_node=brane_node, status="failed", error=str(exc))

    def reconcile(self, db: Session) -> None:
        p_nodes = db.exec(select(ProvisionedNode).where(ProvisionedNode.status == "ready")).all()
        c_nodes = db.exec(select(CoordinatorNode).where(CoordinatorNode.status == "ready")).all()

        seen: set = set()
        to_check = []

        for n in p_nodes:
            if n.brane_node not in seen:
                seen.add(n.brane_node)
                to_check.append((
                    n.brane_node,
                    Path(n.working_dir),
                    PortBlock(n.port_reg, n.port_job, n.port_chk_deliberation, n.port_chk_store, n.port_prx),
                ))

        for n in c_nodes:
            if n.brane_node not in seen:
                seen.add(n.brane_node)
                to_check.append((
                    n.brane_node,
                    Path(n.working_dir),
                    PortBlock(n.port_reg, n.port_job, n.port_chk_deliberation, n.port_chk_store, n.port_prx),
                ))

        for brane_node, working_dir, ports in to_check:
            was_down = not _check_node_running(brane_node)
            if was_down:
                logger.info("Reconcile: node %s is down — restarting", brane_node)
                try:
                    _start_node(working_dir)
                    _health_check("localhost", ports)
                except Exception as exc:
                    logger.error("Reconcile: failed to restart node %s: %s", brane_node, exc)
                    continue
            else:
                logger.info("Reconcile: node %s is up", brane_node)

            if settings.WSL2_MODE:
                try:
                    _extend_brane_fwd(brane_node, ports)
                except Exception as exc:
                    logger.warning("Reconcile: brane-fwd extend failed for %s: %s", brane_node, exc)

        if settings.WSL2_MODE:
            try:
                _extend_brane_fwd_static()
            except Exception as exc:
                logger.warning("Reconcile: static node brane-fwd extension failed: %s", exc)

    def _push_package(self, project_id: int, db: Session) -> None:
        src = db.exec(
            select(PackageSource).where(PackageSource.project_id == project_id)
        ).first()
        if src and src.build_status == "built":
            PackageBuilder().push(src.package_name)
        else:
            logger.info("No built package for project %d — skipping push", project_id)
