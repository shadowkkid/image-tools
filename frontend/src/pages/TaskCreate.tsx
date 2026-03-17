import { useEffect, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  Card,
  Form,
  Input,
  InputNumber,
  Button,
  message,
  Space,
} from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { checkAuth, createTask } from '../api/client';
import LoginModal from '../components/LoginModal';

const { TextArea } = Input;

export default function TaskCreate() {
  const navigate = useNavigate();
  const location = useLocation();
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [loginOpen, setLoginOpen] = useState(false);
  const [loginRegistry, setLoginRegistry] = useState('');

  // Pre-fill form from clone data (via location.state)
  useEffect(() => {
    const state = location.state as Record<string, unknown> | null;
    if (state) {
      form.setFieldsValue(state);
    }
  }, []);

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
    const baseImages = (values.base_images as string)
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
      dataset: values.dataset as string,
      base_images: baseImages,
      push_dir: values.push_dir as string,
      build_args: buildArgs,
      retry_count: (values.retry_count as number) ?? 0,
      concurrency: (values.concurrency as number) ?? 1,
    });

    message.success(`任务 "${res.task_name}" 已创建`);
    navigate(`/tasks/${res.task_id}`);
  };

  const handleLoginSuccess = async () => {
    setLoginOpen(false);
    // Retry submit after login
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

          <Form.Item
            label="数据集"
            name="dataset"
            rules={[{ required: true, message: '请输入数据集名称' }]}
            extra="构建成功的镜像将自动归入该数据集"
          >
            <Input placeholder="例如: swe-bench-verified" />
          </Form.Item>

          <Form.Item
            label="Base 镜像列表"
            name="base_images"
            rules={[{ required: true, message: '请输入至少一个 base 镜像' }]}
            extra="每行一个镜像地址"
          >
            <TextArea
              rows={4}
              placeholder={"ubuntu:22.04\ndebian:bookworm\nnikolaik/python-nodejs:python3.12-nodejs22"}
            />
          </Form.Item>

          <Form.Item
            label="推送目标 (push_dir)"
            name="push_dir"
            rules={[{ required: true, message: '请输入推送目标地址' }]}
          >
            <Input placeholder="例如: registry.sensecore.tech/ccr-sandbox-swe" />
          </Form.Item>

          <Form.Item
            label="Docker Build 参数"
            name="build_args"
            extra="每行一个参数，例如: --build-arg=HTTP_PROXY=http://proxy:8080"
          >
            <TextArea rows={3} placeholder="--build-arg=HTTP_PROXY=http://proxy:8080&#10;--network=host" />
          </Form.Item>

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
