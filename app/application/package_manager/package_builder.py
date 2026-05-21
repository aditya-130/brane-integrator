import logging
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from app.infrastructure.settings import settings

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
            cmd = ["brane", "package", "build"]
            if settings.BRANELET_PATH:
                cmd += ["--init", settings.BRANELET_PATH]
            cmd.append(str(container_yml_path))
            proc = subprocess.run(
                cmd,
                cwd=working_dir,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if proc.returncode != 0:
                combined = f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
                logger.error("brane build failed:\n%s", combined)
                return BuildResult(success=False, stderr=combined)

            # Brane CLI bug: returns exit code 0 even on Docker build failure.
            # Detect failure by checking stdout for the error marker.
            if "failed to build" in proc.stdout.lower():
                combined = f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
                logger.error("brane build failed (exit 0 bug):\n%s", combined)
                return BuildResult(success=False, stderr=combined)

            # Extract image name from stdout (brane prints "Successfully built <name>:<version>")
            image_name = _parse_image_name(proc.stdout) or container_yml_path.parent.name
            return BuildResult(success=True, image_name=image_name)
        except subprocess.TimeoutExpired:
            return BuildResult(success=False, stderr="brane build timed out after 120s")
        except Exception as e:
            logger.error("PackageBuilder.build error: %s", e)
            return BuildResult(success=False, stderr=str(e))

    def _fix_packages_dir_ownership(self) -> None:
        """WSL2/Docker bind-mount quirk: brane-api's packages dir appears as root:root
        inside the container. Chown it to the brane user so the push HTTP handler can write."""
        try:
            container = settings.BRANE_API_CONTAINER or "brane-api"
            packages_path = settings.BRANE_CENTRAL_PACKAGES_PATH or "/home/aditya/brane/nodes/central/packages"
            subprocess.run(
                ["docker", "exec", "-u", "root", container, "chown", "brane:brane", packages_path],
                capture_output=True, timeout=10,
            )
        except Exception as e:
            logger.warning("Could not fix packages dir ownership: %s", e)

    def push(self, package_name: str) -> bool:
        self._fix_packages_dir_ownership()
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
