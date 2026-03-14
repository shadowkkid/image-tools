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
    DOCKER_TAG = "docker_tag"
    DOCKER_PUSH = "docker_push"


ALL_STAGES = [
    StageName.GENERATE_DOCKERFILE,
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

    def __post_init__(self):
        if not self.stages:
            self.stages = [StageInfo(name=s) for s in ALL_STAGES]

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
    build_args: list[str] = field(default_factory=list)
    retry_count: int = 0
    concurrency: int = 1
    source_dir: str = ""
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
