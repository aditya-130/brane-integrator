import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import docker
import docker.errors
from pathlib import Path as _Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.domain.infra import CoordinatorNode, ProvisionedNode, ProjectConfig
from app.domain.package import PackageSource
from app.domain.workflow import Workflow
from app.infrastructure.database import get_db
from app.infrastructure.settings import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@dataclass
class NodeRow:
    brane_node: str
    node_type: str           # "participant" | "coordinator"
    docker_status: str       # "running" | "exited" | "not_found" | "unknown"
    db_status: str
    project_id: int
    user_id: Optional[int]
    port_reg: int
    port_job: int
    working_dir: str
    provisioned_at: Optional[datetime]


@dataclass
class ProjectRow:
    project_id: int
    package_name: str
    package_version: str
    build_status: str
    coordinator_node: Optional[str]
    active_node_count: int
    latest_cycle_id: Optional[int]
    latest_cycle_status: Optional[str]


def _docker_status(brane_node: str) -> str:
    try:
        client = docker.from_env()
        container = client.containers.get(f"brane-job-{brane_node}")
        return container.status
    except docker.errors.NotFound:
        return "not_found"
    except Exception:
        return "unknown"


def _build_node_rows(db: Session) -> list[NodeRow]:
    rows = []
    for n in db.exec(select(ProvisionedNode)).all():
        rows.append(NodeRow(
            brane_node=n.brane_node,
            node_type="participant",
            docker_status=_docker_status(n.brane_node),
            db_status=n.status,
            project_id=n.project_id,
            user_id=n.user_id,
            port_reg=n.port_reg,
            port_job=n.port_job,
            working_dir=n.working_dir,
            provisioned_at=n.provisioned_at,
        ))
    for c in db.exec(select(CoordinatorNode)).all():
        rows.append(NodeRow(
            brane_node=c.brane_node,
            node_type="coordinator",
            docker_status=_docker_status(c.brane_node),
            db_status=c.status,
            project_id=c.project_id,
            user_id=None,
            port_reg=c.port_reg,
            port_job=c.port_job,
            working_dir=c.working_dir,
            provisioned_at=c.provisioned_at,
        ))
    return sorted(rows, key=lambda r: (r.project_id, r.node_type))


def _build_project_rows(db: Session) -> list[ProjectRow]:
    rows = []
    for cfg in db.exec(select(ProjectConfig)).all():
        pkg = db.get(PackageSource, cfg.project_id)
        active_nodes = db.exec(
            select(ProvisionedNode)
            .where(ProvisionedNode.project_id == cfg.project_id)
            .where(ProvisionedNode.status == "ready")
        ).all()
        latest_wf = db.exec(
            select(Workflow)
            .where(Workflow.project_id == cfg.project_id)
            .order_by(Workflow.created_at.desc())
        ).first()
        rows.append(ProjectRow(
            project_id=cfg.project_id,
            package_name=pkg.package_name if pkg else "—",
            package_version=pkg.package_version if pkg else "—",
            build_status=pkg.build_status if pkg else "—",
            coordinator_node=cfg.coordinator_node,
            active_node_count=len(active_nodes),
            latest_cycle_id=latest_wf.cycle_id if latest_wf else None,
            latest_cycle_status=latest_wf.status if latest_wf else None,
        ))
    return rows


@router.get("", response_class=HTMLResponse)
def admin_dashboard(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("admin/dashboard.html", {
        "request": request,
        "node_rows": _build_node_rows(db),
        "project_rows": _build_project_rows(db),
        "api_key": settings.BRANE_INTEGRATOR_API_KEY,
    })


@router.get("/nodes/status", response_class=HTMLResponse)
def nodes_status(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("admin/nodes_fragment.html", {
        "request": request,
        "node_rows": _build_node_rows(db),
    })


def _scan_datasets() -> list[dict]:
    data_base = _Path.home() / "brane" / "data"
    if not data_base.exists():
        return []
    results = []
    for d in sorted(data_base.iterdir()):
        if not d.is_dir():
            continue
        has_csv = (d / "dataset.csv").exists()
        has_yml = (d / "data.yml").exists()
        results.append({"name": d.name, "has_csv": has_csv, "has_yml": has_yml})
    return results


@router.get("/datasets", response_class=HTMLResponse)
def datasets_page(request: Request, msg: str = "", err: str = ""):
    return templates.TemplateResponse("admin/datasets.html", {
        "request": request,
        "datasets": _scan_datasets(),
        "msg": msg,
        "err": err,
    })


@router.post("/datasets/register")
async def register_dataset(
    dataset_name: str = Form(...),
    file: UploadFile = File(...),
):
    from app.application.node_provisioner.node_provisioner import _register_dataset
    from urllib.parse import quote_plus
    try:
        file_bytes = await file.read()
        _register_dataset(dataset_name, file_bytes)
        return RedirectResponse(
            f"/admin/datasets?msg={quote_plus(f'Dataset {dataset_name!r} registered successfully')}",
            status_code=303,
        )
    except Exception as exc:
        return RedirectResponse(
            f"/admin/datasets?err={quote_plus(str(exc)[:300])}",
            status_code=303,
        )


@router.post("/nodes/{brane_node}/push-package")
def push_package(brane_node: str, db: Session = Depends(get_db)):
    node = db.exec(select(ProvisionedNode).where(ProvisionedNode.brane_node == brane_node)).first()
    if not node:
        coord = db.exec(select(CoordinatorNode).where(CoordinatorNode.brane_node == brane_node)).first()
        if not coord:
            return {"success": False, "error": f"Node '{brane_node}' not found"}
        project_id = coord.project_id
    else:
        project_id = node.project_id

    pkg = db.get(PackageSource, project_id)
    if not pkg or pkg.build_status != "built":
        return {"success": False, "error": "Package not built for this project"}

    from app.application.package_manager.package_builder import PackageBuilder
    success = PackageBuilder().push(pkg.package_name)
    return {"success": success, "package": pkg.package_name, "node": brane_node}
