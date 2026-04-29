import json
from pathlib import Path


class BraneHubService:
    def fetch_mock_project_config(self, project_id: int) -> dict:
        path = Path(__file__).parent.parent / "mockdata" / "project_demo.json"
        with open(path) as f:
            return json.load(f)