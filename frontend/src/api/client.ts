import axios from 'axios';
import type {
  TaskSummary,
  TaskDetailData,
  CheckAuthResponse,
  LoginResponse,
  AgentInfo,
  DatasetSummary,
  DatasetImageItem,
  ExportFailedImagesResponse,
  HarborTaskPreview,
} from '../types';

const api = axios.create({ baseURL: '/api' });

// Agents
export async function listAgents(): Promise<{ agents: AgentInfo[] }> {
  const { data } = await api.get('/agents');
  return data;
}

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
  agent: string;
  agent_version: string;
  dataset: string;
  base_images: string[];
  push_dir: string;
  build_args?: string[];
  retry_count?: number;
  concurrency?: number;
  dataset_path?: string;
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

export async function stopTask(taskId: string): Promise<{ success: boolean; message: string }> {
  const { data } = await api.post(`/tasks/${taskId}/stop`);
  return data;
}

// Datasets
export async function listDatasets(
  params: { agent?: string; agent_version?: string; search?: string } = {}
): Promise<{ datasets: DatasetSummary[] }> {
  const { data } = await api.get('/datasets', { params });
  return data;
}

export async function getDatasetImages(
  datasetId: number,
  params: { search?: string; page?: number; page_size?: number } = {}
): Promise<{ images: DatasetImageItem[]; total: number; page: number; page_size: number }> {
  const { data } = await api.get(`/datasets/${datasetId}/images`, { params });
  return data;
}

// Delete operations
export async function deleteTask(taskId: string): Promise<{ success: boolean; message: string }> {
  const { data } = await api.delete(`/tasks/${taskId}`);
  return data;
}

export async function exportFailedImages(taskId: string): Promise<ExportFailedImagesResponse> {
  const { data } = await api.get(`/tasks/${taskId}/failed-images`);
  return data;
}

export async function deleteDataset(datasetId: number): Promise<{ success: boolean; message: string }> {
  const { data } = await api.delete(`/datasets/${datasetId}`);
  return data;
}

export async function parseHarborDataset(
  datasetRef: string
): Promise<{ tasks: HarborTaskPreview[]; total: number; dataset_path: string }> {
  const { data } = await api.post('/harbor/parse-dataset', { dataset_ref: datasetRef });
  return data;
}

export async function batchDeleteDatasetImages(
  datasetId: number,
  ids: number[]
): Promise<{ success: boolean; deleted: number }> {
  const { data } = await api.post(`/datasets/${datasetId}/images/batch-delete`, { ids });
  return data;
}
