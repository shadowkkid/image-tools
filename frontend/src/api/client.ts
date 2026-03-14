import axios from 'axios';
import type {
  TaskSummary,
  TaskDetailData,
  CheckAuthResponse,
  LoginResponse,
} from '../types';

const api = axios.create({ baseURL: '/api' });

// Registry
export async function checkAuth(registry: string): Promise<CheckAuthResponse> {
  const { data } = await api.post('/registry/check-auth', { registry });
  return data;
}

export async function dockerLogin(
  registry: string,
  username: string,
  password: string
): Promise<LoginResponse> {
  const { data } = await api.post('/registry/login', {
    registry,
    username,
    password,
  });
  return data;
}

// Tasks
export interface CreateTaskParams {
  task_name: string;
  deps_image: string;
  base_images: string[];
  push_dir: string;
  build_args?: string[];
  retry_count?: number;
  source_dir?: string;
}

export async function createTask(params: CreateTaskParams): Promise<TaskSummary> {
  const { data } = await api.post('/tasks', params);
  return data;
}

export async function listTasks(): Promise<{ tasks: TaskSummary[] }> {
  const { data } = await api.get('/tasks');
  return data;
}

export async function getTask(taskId: string): Promise<TaskDetailData> {
  const { data } = await api.get(`/tasks/${taskId}`);
  return data;
}
