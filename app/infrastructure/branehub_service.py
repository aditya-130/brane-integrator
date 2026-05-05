import json
import httpx
from pathlib import Path
from app.infrastructure.settings import settings


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
        path = Path(__file__).parent.parent / "mockdata" / "project_demo.json"
        with open(path) as f:
            return json.load(f)

    def send_script_to_branehub(
        self,
        branescript: str,
        traceability_report: str,
        project_id: int,
        cycle_id: int,
        participants_used: list[int],
    ) -> int:
        import uuid
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
                "integrator_metadata": {"participants_used": participants_used},
            },
            timeout=10,
        )
        response.raise_for_status()
        return response.json()["version"]

    def mock_send_bs_to_branehub(
        self,
        branescript: str,
        traceability_report: dict,
        project_id: int,
        cycle_id: int,
    ):
        print(f"Uploading to BraneHub for project {project_id}, cycle {cycle_id}...")
        print("BraneScript:\n", branescript)
        print("Traceability report:\n", json.dumps(traceability_report, indent=2))

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
        response = httpx.post(
            f"{settings.BRANEHUB_BASE_URL}/api/integration/projects/{project_id}/completed",
            headers={
                "X-API-Key": settings.BRANE_INTEGRATOR_API_KEY,
                "Content-Type": "application/json",
            },
            json=body,
            timeout=10,
        )
        if not response.is_success:
            print(f"[send_completed] BraneHub returned {response.status_code}: {response.text}")

    def mock_send_completed(
        self,
        project_id: int,
        cycle_id: int,
        script_version: int,
        status: str,
        result: dict | None,
        error: str | None,
        duration_seconds: int,
    ):
        print(f"[mock_send_completed] project={project_id} cycle={cycle_id} version={script_version}")
        print(f"  status: {status}")
        print(f"  result: {json.dumps(result, indent=2)}")
        print(f"  error: {error}")
        print(f"  duration_seconds: {duration_seconds}")