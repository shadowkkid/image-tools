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
}

export interface TaskSummary {
  task_id: string;
  task_name: string;
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
  status: string;
  deps_image: string;
  push_dir: string;
  build_args: string[];
  retry_count: number;
  concurrency: number;
  source_dir: string;
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
