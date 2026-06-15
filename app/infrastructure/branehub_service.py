import json
import logging
import time
import uuid
from datetime import datetime, timezone
import httpx
from pathlib import Path
from app.infrastructure.settings import settings

logger = logging.getLogger(__name__)


class BraneHubService:
    def fetch_project_config(self, project_id: int) -> dict:
        response = httpx.get(
            f"{settings.BRANEHUB_BASE_URL}/api/integration/projects/{project_id}",
            headers={"X-API-Key": settings.BRANE_INTEGRATOR_API_KEY},
            timeout=10,
        )
        response.raise_for_status()
        return response.json()

    def fetch_mock_project_config(self, project_id: int) -> dict:
        base = Path(__file__).parent.parent / "mockdata"
        specific = base / f"project_{project_id}_demo.json"
        path = specific if specific.exists() else base / "project_demo.json"
        with open(path) as f:
            data = json.load(f)
        data["project_id"] = project_id
        return data

    def send_script_to_branehub(
        self,
        branescript: str,
        traceability_report: str,
        project_id: int,
        cycle_id: int,
        participants_used: list[int],
        note: str | None = None,
    ) -> int:
        if not settings.BRANEHUB_BASE_URL:
            logger.info("BRANEHUB_BASE_URL not set — skipping script upload, returning mock script_version=1")
            return 1
        integrator_metadata: dict = {"participants_used": participants_used}
        if note is not None:
            integrator_metadata["note"] = note
        response = httpx.post(
            f"{settings.BRANEHUB_BASE_URL}/api/integration/projects/{project_id}/script",
            headers={
                "X-API-Key": settings.BRANE_INTEGRATOR_API_KEY,
                "Content-Type": "application/json",
                "Idempotency-Key": str(uuid.uuid4()),
            },
            json={
                "schema_version": "1.0",
                "cycle_id": cycle_id,
                "script_content": branescript,
                "traceability_report": traceability_report,
                "integrator_metadata": integrator_metadata,
            },
            timeout=10,
        )
        response.raise_for_status()
        return response.json()["version"]

    def send_completed(
        self,
        project_id: int,
        cycle_id: int,
        script_version: int,
        status: str,
        result: dict | None,
        error: str | None,
        duration_seconds: int,
        abort_acknowledged: bool = False,
    ):
        if not settings.BRANEHUB_BASE_URL:
            logger.info(
                "BRANEHUB_BASE_URL not set — skipping send_completed (project=%d cycle=%d status=%s)",
                project_id, cycle_id, status,
            )
            return
        metrics: dict = {"duration_seconds": duration_seconds}
        if abort_acknowledged:
            metrics["abort_acknowledged"] = True
        body = {
            "schema_version": "1.0",
            "cycle_id": cycle_id,
            "script_version": script_version,
            "status": status,
            "error": error,
            "metrics": metrics,
        }
        if result is not None:
            body["result"] = result
        url = f"{settings.BRANEHUB_BASE_URL}/api/integration/projects/{project_id}/completed"
        headers = {"X-API-Key": settings.BRANE_INTEGRATOR_API_KEY, "Content-Type": "application/json"}
        for attempt in range(1, 4):
            try:
                response = httpx.post(url, headers=headers, json=body, timeout=10)
                if response.is_success:
                    return
                logger.warning(
                    "send_completed attempt %d/3: BraneHub returned %s — %s",
                    attempt, response.status_code, response.text[:120],
                )
            except Exception as exc:
                logger.warning("send_completed attempt %d/3: request failed — %s", attempt, exc)
            if attempt < 3:
                time.sleep(5 * attempt)

    def send_coordinator_ready(self, project_id: int, status: str, error: str | None = None) -> None:
        if not settings.BRANEHUB_BASE_URL:
            logger.info(
                "BRANEHUB_BASE_URL not set — skipping coordinator-ready callback (project=%d status=%s)",
                project_id, status,
            )
            return
        try:
            httpx.post(
                f"{settings.BRANEHUB_BASE_URL}/api/integration/projects/{project_id}/coordinator-ready",
                headers={"X-API-Key": settings.BRANE_INTEGRATOR_API_KEY},
                json={
                    "status": status,
                    "error": error,
                    "callback_at": datetime.now(timezone.utc).isoformat(),
                },
                timeout=10,
            )
        except Exception as exc:
            logger.warning("BraneHub coordinator-ready callback failed: %s", exc)

    def send_participant_ready(self, project_id: int, user_id: int, brane_node: str) -> None:
        try:
            httpx.post(
                f"{settings.BRANEHUB_BASE_URL}/api/integration/projects/{project_id}/participant-ready",
                headers={"X-API-Key": settings.BRANE_INTEGRATOR_API_KEY},
                json={
                    "user_id": user_id,
                    "brane_node": brane_node,
                    "status": "ready",
                    "callback_at": datetime.now(timezone.utc).isoformat(),
                },
                timeout=10,
            )
        except Exception as exc:
            logger.warning("BraneHub participant-ready callback failed: %s", exc)

    def send_participant_deprovisioned(self, project_id: int, user_id: int) -> None:
        try:
            httpx.post(
                f"{settings.BRANEHUB_BASE_URL}/api/integration/projects/{project_id}/participant-deprovisioned",
                headers={"X-API-Key": settings.BRANE_INTEGRATOR_API_KEY},
                json={
                    "user_id": user_id,
                    "callback_at": datetime.now(timezone.utc).isoformat(),
                },
                timeout=10,
            )
        except Exception as exc:
            logger.warning("BraneHub participant-deprovisioned callback failed: %s", exc)

