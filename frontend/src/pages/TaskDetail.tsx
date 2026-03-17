import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Card,
  Descriptions,
  Table,
  Tag,
  Steps,
  Button,
  Alert,
  Space,
  Spin,
  Modal,
  message,
} from 'antd';
import { ArrowLeftOutlined, ReloadOutlined, StopOutlined, CopyOutlined } from '@ant-design/icons';
import { getTask, stopTask } from '../api/client';
import type { TaskDetailData, ImageDetail, StageDetail } from '../types';

const statusColorMap: Record<string, string> = {
  pending: 'default',
  running: 'processing',
  building: 'processing',
  completed: 'success',
  success: 'success',
  failed: 'error',
  partial_failed: 'warning',
  cancelled: 'warning',
};

const statusLabelMap: Record<string, string> = {
  pending: '等待中',
  running: '运行中',
  building: '构建中',
  completed: '已完成',
  success: '成功',
  failed: '失败',
  partial_failed: '部分失败',
  cancelled: '已取消',
};

const stageLabelMap: Record<string, string> = {
  generate_dockerfile: '生成 Dockerfile',
  docker_build: 'Docker 构建',
  docker_tag: '镜像标签',
  docker_push: '镜像推送',
};

function stageStatusToSteps(status: string): 'wait' | 'process' | 'finish' | 'error' {
  if (status === 'success') return 'finish';
  if (status === 'running') return 'process';
  if (status === 'failed') return 'error';
  return 'wait';
}

function formatSeconds(v: number | null | undefined): string {
  if (v == null) return '-';
  if (v < 60) return `${v.toFixed(1)}s`;
  const m = Math.floor(v / 60);
  const s = v % 60;
  return `${m}m ${s.toFixed(0)}s`;
}

export default function TaskDetail() {
  const { taskId } = useParams<{ taskId: string }>();
  const navigate = useNavigate();
  const [task, setTask] = useState<TaskDetailData | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchTask = async () => {
    if (!taskId) return;
    setLoading(true);
    try {
      const data = await getTask(taskId);
      setTask(data);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTask();
    const timer = setInterval(fetchTask, 3000);
    return () => clearInterval(timer);
  }, [taskId]);

  if (!task && loading) {
    return <Spin size="large" style={{ display: 'block', margin: '100px auto' }} />;
  }

  if (!task) {
    return <Alert type="error" message="任务不存在" style={{ margin: 24 }} />;
  }

  const isRunning = task.status === 'running';

  const handleStop = () => {
    Modal.confirm({
      title: '确认停止任务',
      content: '停止后正在运行的构建将被取消，已完成的镜像不受影响。',
      okText: '停止',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          await stopTask(taskId!);
          message.success('任务已停止');
          fetchTask();
        } catch {
          message.error('停止任务失败');
        }
      },
    });
  };

  const handleClone = () => {
    const cloneData = {
      task_name: `${task.task_name}-copy`,
      agent: task.agent,
      agent_version: task.agent_version,
      dataset: task.dataset,
      push_dir: task.push_dir,
      base_images: task.images.map((img) => img.base_image).join('\n'),
      build_args: task.build_args.join('\n'),
      retry_count: task.retry_count,
      concurrency: task.concurrency,
    };
    navigate('/create', { state: cloneData });
  };

  const expandedRowRender = (record: ImageDetail) => (
    <div style={{ padding: '8px 0' }}>
      <Steps
        size="small"
        items={record.stages.map((s: StageDetail) => ({
          title: stageLabelMap[s.name] || s.name,
          status: stageStatusToSteps(s.status),
          description: s.elapsed_seconds != null ? formatSeconds(s.elapsed_seconds) : undefined,
        }))}
      />
      {record.error_message && (
        <Alert
          type="error"
          message="错误详情"
          description={<pre style={{ whiteSpace: 'pre-wrap', fontSize: 12, margin: 0 }}>{record.error_message}</pre>}
          style={{ marginTop: 12 }}
        />
      )}
      {record.stages
        .filter((s: StageDetail) => s.error_message)
        .map((s: StageDetail) => (
          <Alert
            key={s.name}
            type="error"
            message={`${stageLabelMap[s.name] || s.name} 失败`}
            description={<pre style={{ whiteSpace: 'pre-wrap', fontSize: 12, margin: 0 }}>{s.error_message}</pre>}
            style={{ marginTop: 8 }}
          />
        ))}
    </div>
  );

  const imageColumns = [
    {
      title: 'Base 镜像',
      dataIndex: 'base_image',
      key: 'base_image',
    },
    {
      title: '目标镜像',
      dataIndex: 'target_image',
      key: 'target_image',
      ellipsis: true,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string) => (
        <Tag color={statusColorMap[status] || 'default'}>
          {statusLabelMap[status] || status}
        </Tag>
      ),
    },
    {
      title: '当前阶段',
      dataIndex: 'current_stage',
      key: 'current_stage',
      width: 140,
      render: (v: string | null) => (v ? (stageLabelMap[v] || v) : '-'),
    },
    {
      title: '耗时',
      dataIndex: 'elapsed_seconds',
      key: 'elapsed_seconds',
      width: 100,
      render: (v: number | null) => formatSeconds(v),
    },
    {
      title: '重试次数',
      dataIndex: 'retry_attempts',
      key: 'retry_attempts',
      width: 90,
    },
  ];

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/tasks')}>
          返回列表
        </Button>
        <Button icon={<ReloadOutlined />} onClick={fetchTask} loading={loading}>
          刷新
        </Button>
        {isRunning && (
          <Button danger icon={<StopOutlined />} onClick={handleStop}>
            停止任务
          </Button>
        )}
        <Button icon={<CopyOutlined />} onClick={handleClone}>
          复制任务
        </Button>
        {isRunning && <Tag color="processing">任务运行中，自动刷新</Tag>}
      </Space>

      <Card className="glass-card" title="任务详情" style={{ marginBottom: 16 }}>
        <Descriptions column={2} bordered size="small">
          <Descriptions.Item label="任务名称">{task.task_name}</Descriptions.Item>
          <Descriptions.Item label="状态">
            <Tag color={statusColorMap[task.status]}>{statusLabelMap[task.status] || task.status}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Agent">
            {task.agent}{task.agent_version ? ` / ${task.agent_version}` : ''}
          </Descriptions.Item>
          <Descriptions.Item label="数据集">{task.dataset || '-'}</Descriptions.Item>
          <Descriptions.Item label="推送目标" span={2}>
            <code>{task.push_dir}</code>
          </Descriptions.Item>
          {task.build_args.length > 0 && (
            <Descriptions.Item label="Build 参数" span={2}>
              <code>{task.build_args.join(' ')}</code>
            </Descriptions.Item>
          )}
          <Descriptions.Item label="重试次数">{task.retry_count}</Descriptions.Item>
          <Descriptions.Item label="并行度">{task.concurrency}</Descriptions.Item>
          <Descriptions.Item label="总耗时">{formatSeconds(task.elapsed_seconds)}</Descriptions.Item>
          <Descriptions.Item label="进度">
            {task.completed_images}/{task.total_images} 完成
            {task.failed_images > 0 && <span style={{ color: '#EF6461' }}>, {task.failed_images} 失败</span>}
          </Descriptions.Item>
          <Descriptions.Item label="创建时间">{new Date(task.created_at).toLocaleString()}</Descriptions.Item>
        </Descriptions>
      </Card>

      <Card className="glass-card" title="镜像构建详情">
        <Table
          dataSource={task.images}
          columns={imageColumns}
          rowKey="base_image"
          pagination={false}
          expandable={{ expandedRowRender }}
        />
      </Card>
    </div>
  );
}
