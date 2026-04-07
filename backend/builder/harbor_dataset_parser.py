import hashlib
import logging
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class HarborTaskInfo:
    """Parsed harbor task environment info."""

    task_name: str
    task_dir: str
    docker_image: str  # from task.toml [environment].docker_image
    dockerfile_path: str  # path to environment/Dockerfile
    base_image: str  # resolved base image (docker_image or FROM line)


def parse_harbor_dataset(dataset_path: str) -> list[HarborTaskInfo]:
    """Parse a harbor dataset directory and extract task environment info.

    Each task subdirectory is expected to have:
    - task.toml with optional [environment].docker_image
    - environment/Dockerfile with FROM line (fallback)

    Returns sorted list of HarborTaskInfo.
    Raises ValueError if dataset_path is invalid or no tasks found.
    """
    root = Path(dataset_path)
    if not root.is_dir():
        raise ValueError(f"Dataset path does not exist or is not a directory: {dataset_path}")

    tasks: list[HarborTaskInfo] = []

    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue

        task_toml = entry / "task.toml"
        if not task_toml.exists():
            logger.debug("Skipping %s: no task.toml", entry.name)
            continue

        docker_image = ""
        dockerfile_path = ""
        base_image = ""

        # Parse task.toml for docker_image
        try:
            with open(task_toml, "rb") as f:
                config = tomllib.load(f)
            docker_image = config.get("environment", {}).get("docker_image", "") or ""
        except Exception as e:
            logger.warning("Failed to parse %s: %s", task_toml, e)
            continue

        if docker_image:
            base_image = docker_image
        else:
            # Fallback: parse environment/Dockerfile for FROM line
            df = entry / "environment" / "Dockerfile"
            if df.exists():
                dockerfile_path = str(df)
                base_image = _extract_from_line(df)
            else:
                logger.warning("Skipping %s: no docker_image and no Dockerfile", entry.name)
                continue

        if not base_image:
            logger.warning("Skipping %s: could not resolve base image", entry.name)
            continue

        # Skip unresolved template placeholders (e.g. {docker_image} from adapters)
        if "{" in base_image:
            logger.warning("Skipping %s: base image contains template placeholder: %s", entry.name, base_image)
            continue

        tasks.append(
            HarborTaskInfo(
                task_name=entry.name,
                task_dir=str(entry),
                docker_image=docker_image,
                dockerfile_path=dockerfile_path,
                base_image=base_image,
            )
        )

    if not tasks:
        raise ValueError(f"No valid harbor tasks found in: {dataset_path}")

    return tasks


def compute_template_name(task_name: str, base_image: str) -> str:
    """Compute e2b-style template name from task name and base image.

    Format: {task_name}__{sha256(base_image)[:8]} with / → __ and . → -
    """
    hash_suffix = hashlib.sha256(base_image.encode()).hexdigest()[:8]
    raw = f"{task_name}__{hash_suffix}"
    return raw.replace("/", "__").replace(".", "-")


def _extract_from_line(dockerfile_path: Path) -> str:
    """Extract the last FROM image reference from a Dockerfile."""
    last_from = ""
    try:
        content = dockerfile_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            m = re.match(r"^\s*FROM\s+(\S+)", line, re.IGNORECASE)
            if m:
                last_from = m.group(1)
    except Exception as e:
        logger.warning("Failed to read Dockerfile %s: %s", dockerfile_path, e)
    return last_from
