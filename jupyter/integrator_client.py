import json
import time
from typing import Iterator, Optional

import requests


class IntegratorClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self._headers = {"X-API-Key": api_key, "Content-Type": "application/json"}

    def _get(self, path: str) -> dict:
        resp = requests.get(f"{self.base_url}{path}", headers=self._headers, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: Optional[dict] = None) -> Optional[dict]:
        resp = requests.post(
            f"{self.base_url}{path}", json=body or {}, headers=self._headers, timeout=60
        )
        resp.raise_for_status()
        try:
            return resp.json()
        except Exception:
            return None

    def get_latest_workflow(self, project_id: int) -> dict:
        return self._get(f"/projects/{project_id}/workflows/latest")

    def get_metrics(self, project_id: int, workflow_id: str) -> dict:
        return self._get(f"/projects/{project_id}/workflows/{workflow_id}/metrics")

    def approve_workflow(self, project_id: int, cycle_id: int, script_version: Optional[int]) -> None:
        self._post(f"/projects/{project_id}/workflows/run", {
            "schema_version": "1.0",
            "cycle_id": cycle_id,
            "script_version": script_version or 1,
            "decided_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "decided_by": "researcher",
        })

    def reject_workflow(
        self, project_id: int, cycle_id: int, script_version: Optional[int], reason: str
    ) -> None:
        self._post(f"/projects/{project_id}/workflows/reject", {
            "schema_version": "1.0",
            "cycle_id": cycle_id,
            "script_version": script_version or 1,
            "rejection_reason": reason,
            "decided_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "decided_by": "researcher",
        })

    def poll_execution(
        self, project_id: int, workflow_id: str, interval: int = 5
    ) -> Iterator[dict]:
        while True:
            data = self.get_metrics(project_id, workflow_id)
            yield data
            if data.get("status") in ("completed", "failed", "invalidated"):
                break
            time.sleep(interval)
