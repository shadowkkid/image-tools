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
import { ArrowLeftOutlined, ReloadOutlined, StopOutlined, CopyOutlined, RedoOutlined } from '@ant-design/icons';
import { getTask, stopTask, exportFailedImages } from '../api/client';
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
  docker_build_original: '构建原始镜像',
  docker_build_envd: '注入 envd 层',
  docker_pull: '拉取镜像',
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
  const [imagePage, setImagePage] = useState(1);
  const imagePageSize = 500;

  const fetchTask = async (page?: number) => {
    if (!taskId) return;
    setLoading(true);
    try {
      const data = await getTask(taskId, { image_page: page ?? imagePage, image_page_size: imagePageSize });
      setTask(data);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTask();
    const timer = setInterval(() => fetchTask(), 3000);
    return () => clearInterval(timer);
  }, [taskId, imagePage]);

  if (!task && loading) {
    return <Spin size="large" style={{ display: 'block', margin: '100px auto' }} />;
  }

  if (!task) {
    return <Alert type="error" message="任务不存在" style={{ margin: 24 }} />;
  }

  const isRunning = task.status === 'running';
  const isHarbor = task.agent === 'harbor';

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
    const cloneData: Record<string, unknown> = {
      task_name: `${task.task_name}-copy`,
      agent: task.agent,
      agent_version: task.agent_version,
      dataset: task.dataset,
      push_dir: task.push_dir,
      build_args: task.build_args.join('\n'),
      retry_count: task.retry_count,
      concurrency: task.concurrency,
    };
    if (isHarbor && task.dataset_path) {
      cloneData.dataset_path = task.dataset_path;
      cloneData.dataset_ref = task.dataset_path;
    } else {
      cloneData.base_images = task.images.map((img) => img.base_image).join('\n');
    }
    navigate('/create', { state: cloneData });
  };

  const handleRetryFailed = async () => {
    try {
      const res = await exportFailedImages(taskId!);
      navigate('/create', {
        state: {
          task_name: res.task_name,
          agent: res.agent,
          agent_version: res.agent_version,
          dataset: res.dataset,
          push_dir: res.push_dir,
          base_images: res.base_images.join('\n'),
          build_args: res.build_args.join('\n'),
          retry_count: res.retry_count,
          concurrency: res.concurrency,
          dataset_path: res.dataset_path || undefined,
          dataset_ref: res.dataset_path || undefined,
          harbor_task_names: res.harbor_task_names,
        },
      });
    } catch {
      message.error('导出失败镜像失败');
    }
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

  const handleCopySuccessImages = () => {
    const successImages = task.images
      .filter((img) => img.status === 'success')
      .map((img) => `${img.target_image}\t${img.template_name}`)
      .join('\n');
    if (!successImages) {
      message.warning('没有构建成功的镜像');
      return;
    }
    const count = task.images.filter((img) => img.status === 'success').length;
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(successImages).then(
        () => message.success(`已复制 ${count} 条记录`),
        () => message.error('复制失败'),
      );
    } else {
      // Fallback for non-secure contexts (HTTP)
      const textarea = document.createElement('textarea');
      textarea.value = successImages;
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.select();
      try {
        document.execCommand('copy');
        message.success(`已复制 ${count} 条记录`);
      } catch {
        message.error('复制失败');
      }
      document.body.removeChild(textarea);
    }
  };

  const imageColumns = [
    {
      title: 'Base 镜像',
      dataIndex: 'base_image',
      key: 'base_image',
    },
    ...(isHarbor
      ? [
          {
            title: 'Harbor Task',
            dataIndex: 'harbor_task_name',
            key: 'harbor_task_name',
            width: 160,
            ellipsis: true,
          },
        ]
      : []),
    {
      title: '目标镜像',
      dataIndex: 'target_image',
      key: 'target_image',
      ellipsis: true,
    },
    ...(isHarbor
      ? [
          {
            title: 'Template Name',
            dataIndex: 'template_name',
            key: 'template_name',
            width: 200,
            ellipsis: true,
          },
        ]
      : []),
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
        <Button icon={<ReloadOutlined />} onClick={() => fetchTask()} loading={loading}>
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
        {!isRunning && task.failed_images > 0 && (
          <Button icon={<RedoOutlined />} onClick={handleRetryFailed}>
            重试失败镜像
          </Button>
        )}
        {isHarbor && task.completed_images > 0 && (
          <Button icon={<CopyOutlined />} onClick={handleCopySuccessImages}>
            批量复制成功镜像
          </Button>
        )}
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
          pagination={{
            current: imagePage,
            pageSize: imagePageSize,
            total: task.total_images,
            showTotal: (total) => `共 ${total} 个镜像`,
            onChange: (page) => { setImagePage(page); fetchTask(page); },
          }}
          expandable={{ expandedRowRender }}
        />
      </Card>
    </div>
  );
}
