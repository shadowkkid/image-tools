from pydantic import BaseModel


# ---- Registry ----

class CheckAuthRequest(BaseModel):
    registry: str


class CheckAuthResponse(BaseModel):
    authenticated: bool
    registry: str
    message: str


class LoginRequest(BaseModel):
    registry: str
    username: str
    password: str


class LoginResponse(BaseModel):
    success: bool
    message: str


# ---- Tasks ----

class CreateTaskRequest(BaseModel):
    task_name: str
    deps_image: str
    base_images: list[str]
    push_dir: str
    build_args: list[str] = []
    retry_count: int = 0
    source_dir: str | None = None


class StageDetail(BaseModel):
    name: str
    status: str
    elapsed_seconds: float | None = None
    error_message: str | None = None


class ImageDetail(BaseModel):
    base_image: str
    target_image: str
    status: str
    current_stage: str | None = None
    elapsed_seconds: float | None = None
    retry_attempts: int = 0
    error_message: str | None = None
    stages: list[StageDetail] = []


class TaskSummary(BaseModel):
    task_id: str
    task_name: str
    status: str
    total_images: int
    completed_images: int
    failed_images: int
    created_at: str
    elapsed_seconds: float | None = None


class TaskDetail(BaseModel):
    task_id: str
    task_name: str
    status: str
    deps_image: str
    push_dir: str
    build_args: list[str]
    retry_count: int
    source_dir: str
    created_at: str
    finished_at: str | None = None
    elapsed_seconds: float | None = None
    total_images: int
    completed_images: int
    failed_images: int
    images: list[ImageDetail] = []


class TaskListResponse(BaseModel):
    tasks: list[TaskSummary]
