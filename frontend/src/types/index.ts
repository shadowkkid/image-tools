export interface StageDetail {
  name: string;
  status: string;
  elapsed_seconds: number | null;
  error_message: string | null;
}

export interface ImageDetail {
  base_image: string;
  target_image: string;
  status: string;
  current_stage: string | null;
  elapsed_seconds: number | null;
  retry_attempts: number;
  error_message: string | null;
  stages: StageDetail[];
  template_name: string;
  harbor_task_name: string;
}

export interface TaskSummary {
  task_id: string;
  task_name: string;
  agent: string;
  agent_version: string;
  dataset: string;
  status: string;
  total_images: number;
  completed_images: number;
  failed_images: number;
  created_at: string;
  elapsed_seconds: number | null;
}

export interface TaskDetailData {
  task_id: string;
  task_name: string;
  agent: string;
  agent_version: string;
  dataset: string;
  status: string;
  deps_image: string;
  push_dir: string;
  build_args: string[];
  retry_count: number;
  concurrency: number;
  dataset_path: string;
  created_at: string;
  finished_at: string | null;
  elapsed_seconds: number | null;
  total_images: number;
  completed_images: number;
  failed_images: number;
  images: ImageDetail[];
}

export interface CheckAuthResponse {
  authenticated: boolean;
  registry: string;
  message: string;
}

export interface LoginResponse {
  success: boolean;
  message: string;
}

export interface AgentInfo {
  name: string;
  has_versions: boolean;
  versions: string[];
}

export interface DatasetSummary {
  id: number;
  name: string;
  agent: string;
  agent_version: string;
  image_count: number;
  created_at: string;
}

export interface DatasetImageItem {
  id: number;
  image_name: string;
  task_id: string;
  task_name: string;
  created_at: string;
}

export interface ExportFailedImagesResponse {
  task_name: string;
  agent: string;
  agent_version: string;
  dataset: string;
  base_images: string[];
  push_dir: string;
  build_args: string[];
  retry_count: number;
  concurrency: number;
  dataset_path: string;
  harbor_task_names: string[];
}

export interface HarborTaskPreview {
  task_name: string;
  base_image: string;
  has_dockerfile: boolean;
  has_docker_image: boolean;
}
