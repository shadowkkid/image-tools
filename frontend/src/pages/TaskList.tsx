import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, Table, Tag, Button, Space } from 'antd';
import { PlusOutlined, ReloadOutlined, ArrowLeftOutlined } from '@ant-design/icons';
import { listTasks } from '../api/client';
import type { TaskSummary } from '../types';

const statusColorMap: Record<string, string> = {
  pending: 'default',
  running: 'processing',
  completed: 'success',
  failed: 'error',
  partial_failed: 'warning',
  cancelled: 'warning',
};

const statusLabelMap: Record<string, string> = {
  pending: '等待中',
  running: '运行中',
  completed: '已完成',
  failed: '失败',
  partial_failed: '部分失败',
  cancelled: '已取消',
};

export default function TaskList() {
  const navigate = useNavigate();
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchTasks = async () => {
    setLoading(true);
    try {
      const res = await listTasks();
      setTasks(res.tasks);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTasks();
    const timer = setInterval(fetchTasks, 3000);
    return () => clearInterval(timer);
  }, []);

  const columns = [
    {
      title: '任务名称',
      dataIndex: 'task_name',
      key: 'task_name',
      render: (text: string, record: TaskSummary) => (
        <a onClick={() => navigate(`/tasks/${record.task_id}`)}>{text}</a>
      ),
    },
    {
      title: 'Agent',
      key: 'agent',
      width: 160,
      render: (_: unknown, record: TaskSummary) =>
        record.agent
          ? record.agent_version
            ? `${record.agent} / ${record.agent_version}`
            : record.agent
          : '-',
    },
    {
      title: '数据集',
      dataIndex: 'dataset',
      key: 'dataset',
      width: 160,
      render: (text: string) => text || '-',
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 120,
      render: (status: string) => (
        <Tag color={statusColorMap[status] || 'default'}>
          {statusLabelMap[status] || status}
        </Tag>
      ),
    },
    {
      title: '进度',
      key: 'progress',
      width: 120,
      render: (_: unknown, record: TaskSummary) => (
        <span>
          {record.completed_images}/{record.total_images}
          {record.failed_images > 0 && (
            <span style={{ color: '#EF6461', marginLeft: 4 }}>
              ({record.failed_images} 失败)
            </span>
          )}
        </span>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 200,
      render: (t: string) => new Date(t).toLocaleString(),
    },
    {
      title: '耗时',
      dataIndex: 'elapsed_seconds',
      key: 'elapsed_seconds',
      width: 120,
      render: (v: number | null) => (v != null ? `${v.toFixed(1)}s` : '-'),
    },
  ];

  return (
    <Card
      className="glass-card"
      title="构建任务列表"
      extra={
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/')}>
            首页
          </Button>
          <Button icon={<ReloadOutlined />} onClick={fetchTasks} loading={loading}>
            刷新
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/create')}>
            新建任务
          </Button>
        </Space>
      }
    >
      <Table
        dataSource={tasks}
        columns={columns}
        rowKey="task_id"
        loading={loading}
        pagination={false}
        onRow={(record) => ({
          onClick: () => navigate(`/tasks/${record.task_id}`),
          style: { cursor: 'pointer' },
        })}
      />
    </Card>
  );
}
