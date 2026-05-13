import logging
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_PUSH_RETRIES = 3
_PUSH_RETRY_DELAY = 5  # seconds


@dataclass
class BuildResult:
    success: bool
    image_name: str | None = None
    stderr: str | None = None


class PackageBuilder:

    def build(self, working_dir: Path, container_yml_path: Path) -> BuildResult:
        try:
            proc = subprocess.run(
                ["brane", "package", "build", str(container_yml_path)],
                cwd=working_dir,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if proc.returncode != 0:
                logger.error("brane build failed: %s", proc.stderr)
                return BuildResult(success=False, stderr=proc.stderr)

            # Extract image name from stdout (brane prints "Successfully built <name>:<version>")
            image_name = _parse_image_name(proc.stdout) or container_yml_path.parent.name
            return BuildResult(success=True, image_name=image_name)
        except subprocess.TimeoutExpired:
            return BuildResult(success=False, stderr="brane build timed out after 120s")
        except Exception as e:
            logger.error("PackageBuilder.build error: %s", e)
            return BuildResult(success=False, stderr=str(e))

    def push(self, package_name: str) -> bool:
        for attempt in range(1, _PUSH_RETRIES + 1):
            try:
                proc = subprocess.run(
                    ["brane", "package", "push", package_name],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if proc.returncode == 0:
                    return True
                logger.warning(
                    "brane push attempt %d/%d failed: %s", attempt, _PUSH_RETRIES, proc.stderr
                )
            except subprocess.TimeoutExpired:
                logger.warning("brane push attempt %d/%d timed out", attempt, _PUSH_RETRIES)
            except Exception as e:
                logger.error("brane push error on attempt %d: %s", attempt, e)

            if attempt < _PUSH_RETRIES:
                time.sleep(_PUSH_RETRY_DELAY)

        return False


def _parse_image_name(stdout: str) -> str | None:
    for line in stdout.splitlines():
        if "successfully built" in line.lower():
            parts = line.split()
            if parts:
                return parts[-1]
    return None
