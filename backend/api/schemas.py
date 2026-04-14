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
    agent: str = ""
    agent_version: str = ""
    dataset: str = ""
    base_images: list[str] = []
    push_dir: str = ""
    build_args: list[str] = []
    retry_count: int = 0
    concurrency: int = 2
    dataset_path: str = ""
    harbor_task_names: list[str] = []
    build_type: str = "opensource"
    dockerfile_content: str = ""
    tag_mode: str = ""
    tag_suffix: str = ""


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
    template_name: str = ""
    harbor_task_name: str = ""


class TaskSummary(BaseModel):
    task_id: str
    task_name: str
    agent: str
    agent_version: str
    dataset: str
    status: str
    build_mode: str = "build"
    total_images: int
    completed_images: int
    failed_images: int
    created_at: str
    elapsed_seconds: float | None = None


class TaskDetail(BaseModel):
    task_id: str
    task_name: str
    agent: str
    agent_version: str
    dataset: str
    status: str
    build_mode: str = "build"
    deps_image: str
    push_dir: str
    build_args: list[str]
    retry_count: int
    concurrency: int
    dataset_path: str = ""
    dockerfile_content: str = ""
    tag_mode: str = ""
    tag_suffix: str = ""
    created_at: str
    finished_at: str | None = None
    elapsed_seconds: float | None = None
    total_images: int
    completed_images: int
    failed_images: int
    images: list[ImageDetail] = []


class TaskListResponse(BaseModel):
    tasks: list[TaskSummary]


# ---- Agents ----

class AgentVersion(BaseModel):
    version: str


class AgentInfo(BaseModel):
    name: str
    has_versions: bool
    versions: list[str] = []


class AgentListResponse(BaseModel):
    agents: list[AgentInfo]


# ---- Datasets ----

class BatchDeleteRequest(BaseModel):
    ids: list[int]


class DatasetSummary(BaseModel):
    id: int
    name: str
    agent: str
    agent_version: str
    image_count: int
    created_at: str


class DatasetListResponse(BaseModel):
    datasets: list[DatasetSummary]


class DatasetImageItem(BaseModel):
    id: int
    image_name: str
    task_id: str
    task_name: str
    created_at: str


class DatasetImageListResponse(BaseModel):
    images: list[DatasetImageItem]
    total: int
    page: int
    page_size: int


# ---- Export Failed Images ----

class ExportFailedImagesResponse(BaseModel):
    task_name: str
    agent: str
    agent_version: str
    dataset: str
    base_images: list[str]
    push_dir: str
    build_args: list[str]
    retry_count: int
    concurrency: int
    dataset_path: str = ""
    harbor_task_names: list[str] = []
    build_type: str = "opensource"
    dockerfile_content: str = ""
    tag_mode: str = ""
    tag_suffix: str = ""


# ---- Harbor Dataset ----

class ParseDatasetRequest(BaseModel):
    dataset_ref: str


class HarborTaskPreview(BaseModel):
    task_name: str
    base_image: str
    has_dockerfile: bool
    has_docker_image: bool


class ParseDatasetResponse(BaseModel):
    tasks: list[HarborTaskPreview]
    total: int
    dataset_path: str = ""
