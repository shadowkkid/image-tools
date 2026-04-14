import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL_FAILED = "partial_failed"
    CANCELLED = "cancelled"


class ImageBuildStatus(str, Enum):
    PENDING = "pending"
    BUILDING = "building"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class StageName(str, Enum):
    GENERATE_DOCKERFILE = "generate_dockerfile"
    DOCKER_BUILD = "docker_build"
    DOCKER_PULL = "docker_pull"
    DOCKER_TAG = "docker_tag"
    DOCKER_PUSH = "docker_push"
    DOCKER_BUILD_ORIGINAL = "docker_build_original"
    DOCKER_BUILD_ENVD = "docker_build_envd"


ALL_STAGES = [
    StageName.GENERATE_DOCKERFILE,
    StageName.DOCKER_BUILD,
    StageName.DOCKER_TAG,
    StageName.DOCKER_PUSH,
]

RETAG_STAGES = [
    StageName.DOCKER_PULL,
    StageName.DOCKER_TAG,
    StageName.DOCKER_PUSH,
]

HARBOR_STAGES = [
    StageName.DOCKER_BUILD_ORIGINAL,
    StageName.DOCKER_BUILD_ENVD,
    StageName.DOCKER_TAG,
    StageName.DOCKER_PUSH,
]

SCRIPT_BUILD_STAGES = [
    StageName.DOCKER_BUILD,
    StageName.DOCKER_TAG,
    StageName.DOCKER_PUSH,
]


@dataclass
class StageInfo:
    name: StageName
    status: StageStatus = StageStatus.PENDING
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None

    @property
    def elapsed_seconds(self) -> float | None:
        if self.started_at is None:
            return None
        end = self.finished_at or datetime.now()
        return round((end - self.started_at).total_seconds(), 2)


@dataclass
class ImageBuildInfo:
    base_image: str
    target_image: str
    status: ImageBuildStatus = ImageBuildStatus.PENDING
    stages: list[StageInfo] = field(default_factory=list)
    retry_attempts: int = 0
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    stage_names: list[StageName] = field(default_factory=list)
    template_name: str = ""
    harbor_task_name: str = ""
    harbor_dockerfile_path: str = ""
    harbor_docker_image: str = ""

    def __post_init__(self):
        if not self.stages:
            names = self.stage_names if self.stage_names else ALL_STAGES
            self.stages = [StageInfo(name=s) for s in names]

    @property
    def elapsed_seconds(self) -> float | None:
        if self.started_at is None:
            return None
        end = self.finished_at or datetime.now()
        return round((end - self.started_at).total_seconds(), 2)

    @property
    def current_stage(self) -> str | None:
        for stage in self.stages:
            if stage.status == StageStatus.RUNNING:
                return stage.name.value
        return None


@dataclass
class BuildTask:
    task_name: str
    deps_image: str
    push_dir: str
    base_images: list[str]
    agent: str = ""
    agent_version: str = ""
    dataset: str = ""
    build_args: list[str] = field(default_factory=list)
    retry_count: int = 0
    concurrency: int = 2
    source_dir: str = ""
    build_mode: str = "build"
    dataset_path: str = ""
    envd_binary_path: str = ""
    dockerfile_content: str = ""
    tag_mode: str = ""
    tag_suffix: str = ""
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: TaskStatus = TaskStatus.PENDING
    images: list[ImageBuildInfo] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    finished_at: datetime | None = None

    @property
    def total_images(self) -> int:
        return len(self.images)

    @property
    def completed_images(self) -> int:
        return sum(1 for img in self.images if img.status == ImageBuildStatus.SUCCESS)

    @property
    def failed_images(self) -> int:
        return sum(1 for img in self.images if img.status == ImageBuildStatus.FAILED)

    @property
    def elapsed_seconds(self) -> float | None:
        end = self.finished_at or datetime.now()
        return round((end - self.created_at).total_seconds(), 2)
