import { useEffect, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  Card,
  Form,
  Input,
  InputNumber,
  Select,
  Button,
  message,
  Space,
  Table,
} from 'antd';
import { ArrowLeftOutlined, SearchOutlined } from '@ant-design/icons';
import { checkAuth, createTask, listAgents, parseHarborDataset } from '../api/client';
import LoginModal from '../components/LoginModal';
import type { AgentInfo, HarborTaskPreview } from '../types';

const { TextArea } = Input;

export default function TaskCreate() {
  const navigate = useNavigate();
  const location = useLocation();
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [loginOpen, setLoginOpen] = useState(false);
  const [loginRegistry, setLoginRegistry] = useState('');
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<AgentInfo | null>(null);
  const [harborPreview, setHarborPreview] = useState<HarborTaskPreview[]>([]);
  const [parsing, setParsing] = useState(false);
  const [resolvedDatasetPath, setResolvedDatasetPath] = useState('');
  const [retryBaseImages, setRetryBaseImages] = useState<string[]>([]);
  const [retryHarborTaskNames, setRetryHarborTaskNames] = useState<string[]>([]);

  const isHarbor = selectedAgent?.name === 'harbor';

  useEffect(() => {
    listAgents().then((res) => {
      setAgents(res.agents);
      // If only one agent, auto-select it
      if (res.agents.length === 1) {
        const agent = res.agents[0];
        setSelectedAgent(agent);
        form.setFieldsValue({ agent: agent.name });
        if (agent.has_versions && agent.versions.length === 1) {
          form.setFieldsValue({ agent_version: agent.versions[0] });
        }
      }
    });
  }, []);

  // Pre-fill form from clone data (via location.state)
  useEffect(() => {
    const state = location.state as Record<string, unknown> | null;
    if (state) {
      form.setFieldsValue(state);
      // Restore selectedAgent for version dropdown visibility
      if (state.agent && agents.length > 0) {
        const a = agents.find((ag) => ag.name === state.agent);
        if (a) setSelectedAgent(a);
      }
      // Store retry base_images in React state (form store drops unrendered fields)
      if (state.base_images && typeof state.base_images === 'string') {
        const images = (state.base_images as string).split('\n').map(s => s.trim()).filter(Boolean);
        if (images.length > 0) setRetryBaseImages(images);
      }
      // Store retry harbor_task_names for harbor mode filtering
      if (Array.isArray(state.harbor_task_names) && (state.harbor_task_names as string[]).length > 0) {
        setRetryHarborTaskNames(state.harbor_task_names as string[]);
      }
    }
  }, [agents]);

  const handleAgentChange = (agentName: string) => {
    const agent = agents.find((a) => a.name === agentName) || null;
    setSelectedAgent(agent);
    setHarborPreview([]);
    setResolvedDatasetPath('');
    form.setFieldsValue({ agent_version: undefined });
    // Auto-select if only one version
    if (agent?.has_versions && agent.versions.length === 1) {
      form.setFieldsValue({ agent_version: agent.versions[0] });
    }
  };

  const handleParseDataset = async () => {
    const datasetRef = form.getFieldValue('dataset_ref');
    if (!datasetRef) {
      message.warning('请先输入数据集');
      return;
    }
    setParsing(true);
    try {
      const res = await parseHarborDataset(datasetRef);
      let tasks = res.tasks;
      // Only apply retry filters when the resolved dataset matches the original task's dataset.
      // If the user changed dataset_ref to a different dataset, clear old filters entirely
      // so they don't affect the create request either.
      const state = location.state as Record<string, unknown> | null;
      const originalDatasetPath = state?.dataset_path as string | undefined;
      const datasetMatches = originalDatasetPath && res.dataset_path === originalDatasetPath;
      if (!datasetMatches) {
        setRetryHarborTaskNames([]);
        setRetryBaseImages([]);
      } else if (retryHarborTaskNames.length > 0) {
        const allowSet = new Set(retryHarborTaskNames);
        tasks = tasks.filter((t) => allowSet.has(t.task_name));
      } else if (retryBaseImages.length > 0) {
        const allowSet = new Set(retryBaseImages);
        tasks = tasks.filter((t) => allowSet.has(t.base_image));
      }
      setHarborPreview(tasks);
      setResolvedDatasetPath(res.dataset_path);
      message.success(`解析到 ${tasks.length} 个任务`);
    } catch {
      message.error('解析数据集失败，请检查数据集名称');
    } finally {
      setParsing(false);
    }
  };

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      setLoading(true);

      // Check push_dir auth first
      const authRes = await checkAuth(values.push_dir);
      if (!authRes.authenticated) {
        setLoginRegistry(authRes.registry);
        setLoginOpen(true);
        setLoading(false);
        return;
      }

      await doCreateTask(values);
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'response' in err) {
        message.error('提交失败，请检查输入');
      }
    } finally {
      setLoading(false);
    }
  };

  const doCreateTask = async (values: Record<string, unknown>) => {
    const isHarborAgent = values.agent === 'harbor';
    const baseImages = isHarborAgent
      ? retryBaseImages
      : ((values.base_images as string) || '')
          .split('\n')
          .map((s: string) => s.trim())
          .filter(Boolean);
    const buildArgs = values.build_args
      ? (values.build_args as string)
          .split('\n')
          .map((s: string) => s.trim())
          .filter(Boolean)
      : [];

    const res = await createTask({
      task_name: values.task_name as string,
      agent: values.agent as string,
      agent_version: (values.agent_version as string) || '',
      dataset: values.dataset as string,
      base_images: baseImages,
      push_dir: values.push_dir as string,
      build_args: buildArgs,
      retry_count: (values.retry_count as number) ?? 0,
      concurrency: (values.concurrency as number) ?? 1,
      dataset_path: isHarborAgent ? (resolvedDatasetPath || (values.dataset_ref as string) || '') : undefined,
      harbor_task_names: isHarborAgent ? retryHarborTaskNames : undefined,
    });

    message.success(`任务 "${res.task_name}" 已创建`);
    navigate(`/tasks/${res.task_id}`);
  };

  const handleLoginSuccess = async () => {
    setLoginOpen(false);
    const values = form.getFieldsValue();
    setLoading(true);
    try {
      await doCreateTask(values);
    } catch {
      message.error('创建任务失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <Card className="glass-card" title="创建构建任务" style={{ maxWidth: 720, margin: '0 auto' }}>
        <Form
          form={form}
          layout="vertical"
          initialValues={{ retry_count: 0, concurrency: 2 }}
        >
          <Form.Item
            label="任务名称"
            name="task_name"
            rules={[{ required: true, message: '请输入任务名称' }]}
          >
            <Input placeholder="例如: build-runtime-v1" />
          </Form.Item>

          <Space size={12} style={{ display: 'flex' }}>
            <Form.Item
              label="Agent"
              name="agent"
              rules={[{ required: true, message: '请选择 Agent' }]}
              style={{ flex: 1 }}
            >
              <Select
                placeholder="选择 Agent"
                onChange={handleAgentChange}
                options={agents.map((a) => ({ label: a.name, value: a.name }))}
              />
            </Form.Item>

            {selectedAgent?.has_versions && (
              <Form.Item
                label="Version"
                name="agent_version"
                rules={[{ required: true, message: '请选择版本' }]}
                style={{ flex: 1 }}
              >
                <Select
                  placeholder="选择版本"
                  options={selectedAgent.versions.map((v) => ({ label: v, value: v }))}
                />
              </Form.Item>
            )}
          </Space>

          <Form.Item
            label="数据集"
            name="dataset"
            rules={[{ required: true, message: '请输入数据集名称' }]}
            extra="构建成功的镜像将自动归入该数据集（同 Agent 下）"
          >
            <Input placeholder="例如: swe-bench-verified" />
          </Form.Item>

          {isHarbor ? (
            <>
              <Form.Item
                label="Harbor 数据集"
                name="dataset_ref"
                rules={[{ required: true, message: '请输入 harbor 数据集' }]}
                extra="格式: dataset@version（如 hello-world@1.0），也支持本地路径"
              >
                <Input placeholder="hello-world@1.0" />
              </Form.Item>
              <Form.Item>
                <Button icon={<SearchOutlined />} onClick={handleParseDataset} loading={parsing}>
                  解析预览
                </Button>
              </Form.Item>
              {harborPreview.length > 0 && (
                <Form.Item label={`预览（${harborPreview.length} 个任务）`}>
                  <Table
                    dataSource={harborPreview}
                    rowKey="task_name"
                    size="small"
                    pagination={{ pageSize: 50, showTotal: (total) => `共 ${total} 个任务`, size: 'small' }}
                    scroll={{ y: 300 }}
                    columns={[
                      { title: 'Task', dataIndex: 'task_name', key: 'task_name' },
                      { title: 'Base Image', dataIndex: 'base_image', key: 'base_image', ellipsis: true },
                      {
                        title: '类型',
                        key: 'type',
                        width: 120,
                        render: (_: unknown, r: HarborTaskPreview) =>
                          r.has_docker_image ? 'Prebuilt' : r.has_dockerfile ? 'Dockerfile' : '-',
                      },
                    ]}
                  />
                </Form.Item>
              )}
            </>
          ) : (
            <Form.Item
              label="Base 镜像列表"
              name="base_images"
              rules={[{ required: true, message: '请输入至少一个 base 镜像' }]}
              extra={selectedAgent && !selectedAgent.has_versions
                ? "每行一个镜像地址，将直接拉取并打上新 tag 推送"
                : "每行一个镜像地址"
              }
            >
              <TextArea
                rows={4}
                placeholder={"ubuntu:22.04\ndebian:bookworm\nnikolaik/python-nodejs:python3.12-nodejs22"}
              />
            </Form.Item>
          )}

          <Form.Item
            label="推送目标 (push_dir)"
            name="push_dir"
            rules={[{ required: true, message: '请输入推送目标地址' }]}
          >
            <Input placeholder="例如: registry.sensecore.tech/ccr-sandbox-swe" />
          </Form.Item>

          {!isHarbor && selectedAgent?.has_versions !== false && (
            <Form.Item
              label="Docker Build 参数"
              name="build_args"
              extra="每行一个参数，例如: --build-arg=HTTP_PROXY=http://proxy:8080"
            >
              <TextArea rows={3} placeholder="--build-arg=HTTP_PROXY=http://proxy:8080&#10;--network=host" />
            </Form.Item>
          )}

          <Form.Item label="每条命令重试次数" name="retry_count">
            <InputNumber min={0} max={10} style={{ width: 120 }} />
          </Form.Item>

          <Form.Item
            label="并行度"
            name="concurrency"
            extra="同时构建的镜像数量，建议 1-4"
          >
            <InputNumber min={1} max={10} style={{ width: 120 }} />
          </Form.Item>

          <Form.Item>
            <Space>
              <Button type="primary" onClick={handleSubmit} loading={loading}>
                提交任务
              </Button>
              <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/tasks')}>
                返回列表
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Card>

      <LoginModal
        open={loginOpen}
        registry={loginRegistry}
        onSuccess={handleLoginSuccess}
        onCancel={() => setLoginOpen(false)}
      />
    </>
  );
}
