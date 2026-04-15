import hashlib
import logging
import os
import re
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

HARBOR_DATASET_CACHE = Path.home() / ".cache" / "harbor" / "image-tools-datasets"


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


def compute_template_name(dataset_name: str, task_name: str, task_dir: str) -> str:
    """Compute e2b-style template name matching harbor's naming convention.

    Format: {dataset_name}__{task_name}__{dirhash(environment_dir, 'sha256')[:8]}
    with . → -
    """
    from dirhash import dirhash

    env_dir = os.path.join(task_dir, "environment")
    if os.path.isdir(env_dir):
        hash_suffix = dirhash(env_dir, "sha256")[:8]
    else:
        hash_suffix = hashlib.sha256(task_name.encode()).hexdigest()[:8]
    raw = f"{dataset_name}__{task_name}__{hash_suffix}"
    return raw.replace(".", "-")


def extract_dataset_name(dataset_path: str) -> str:
    """Extract dataset name (without version) from a dataset path.

    For downloaded datasets: /path/to/terminal-bench-2.0 → terminal-bench
    For local paths: use directory basename, strip trailing -version if present.
    """
    basename = os.path.basename(dataset_path.rstrip("/"))
    # Strip trailing version suffix like -2.0, -1.0.3, -head
    m = re.match(r"^(.+?)-([\d]+[\d.]*|head)$", basename)
    if m:
        return m.group(1)
    return basename


def _extract_from_line(dockerfile_path: Path) -> str:
    """Extract the last FROM image reference from a Dockerfile."""
    last_from = ""
    try:
        content = dockerfile_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            m = re.match(r"^\s*FROM\s+(.+)", line, re.IGNORECASE)
            if m:
                # Skip --platform and other flags to find the actual image name
                parts = m.group(1).split()
                for part in parts:
                    if not part.startswith("--"):
                        # Strip AS alias
                        last_from = part.split()[0]
                        break
    except Exception as e:
        logger.warning("Failed to read Dockerfile %s: %s", dockerfile_path, e)
    return last_from


def _is_dataset_ref(value: str) -> bool:
    """Check if value looks like a dataset@version ref rather than a local path."""
    return not Path(value).is_absolute() and not value.startswith(".")


def download_harbor_dataset(dataset_ref: str, overwrite: bool = False) -> str:
    """Download a harbor dataset using `harbor dataset download` CLI.

    Args:
        dataset_ref: Dataset reference in format 'name@version' or 'name'.
        overwrite: If True, re-download even if cached.

    Returns:
        Local path to the downloaded dataset directory.

    Raises:
        ValueError: If download fails.
    """
    if not shutil.which("harbor"):
        raise ValueError("harbor CLI not found. Please install harbor first.")

    # Parse ref to build cache path
    if "@" in dataset_ref:
        name, version = dataset_ref.rsplit("@", 1)
    else:
        name, version = dataset_ref, "head"

    safe_name = name.replace("/", "__")
    output_dir = HARBOR_DATASET_CACHE / f"{safe_name}-{version}"

    if output_dir.exists() and not overwrite:
        # Verify it has at least one task.toml
        if any(output_dir.rglob("task.toml")):
            logger.info("Using cached dataset at %s", output_dir)
            return str(output_dir)
        # Cache is empty/corrupt, re-download
        shutil.rmtree(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = ["harbor", "dataset", "download", dataset_ref, "-o", str(output_dir)]
    if overwrite:
        cmd.append("--overwrite")

    logger.info("Downloading harbor dataset: %s -> %s", dataset_ref, output_dir)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600,
        )
        if result.returncode != 0:
            error_msg = result.stderr.strip() or result.stdout.strip()
            raise ValueError(f"harbor dataset download failed: {error_msg}")
    except subprocess.TimeoutExpired:
        raise ValueError(f"harbor dataset download timed out for: {dataset_ref}")

    if not any(output_dir.rglob("task.toml")):
        raise ValueError(f"Downloaded dataset has no valid tasks: {dataset_ref}")

    return str(output_dir)


def resolve_and_parse(dataset_ref: str) -> tuple[str, list[HarborTaskInfo]]:
    """Resolve a dataset reference and parse it.

    Accepts either a local path or a dataset@version ref.
    Returns (local_path, parsed_tasks).
    """
    if _is_dataset_ref(dataset_ref):
        local_path = download_harbor_dataset(dataset_ref)
    else:
        local_path = dataset_ref

    tasks = parse_harbor_dataset(local_path)
    return local_path, tasks
