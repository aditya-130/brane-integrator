import json
from pathlib import Path


class BraneHubService:
    def fetch_mock_project_config(self, project_id: int) -> dict:
        path = Path(__file__).parent.parent / "mockdata" / "project_demo.json"
        with open(path) as f:
            return json.load(f)

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