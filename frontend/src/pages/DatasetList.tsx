import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, Table, Input, Button, Space, Modal, message } from 'antd';
import { ArrowLeftOutlined, ReloadOutlined, DeleteOutlined } from '@ant-design/icons';
import { listDatasets, deleteDataset } from '../api/client';
import type { DatasetSummary } from '../types';

const { Search } = Input;

export default function DatasetList() {
  const navigate = useNavigate();
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');

  const fetchDatasets = async (q: string = search) => {
    setLoading(true);
    try {
      const res = await listDatasets({ search: q });
      setDatasets(res.datasets);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDatasets();
  }, []);

  const handleSearch = (value: string) => {
    setSearch(value);
    fetchDatasets(value);
  };

  const handleDeleteDataset = (id: number, name: string) => {
    Modal.confirm({
      title: '确认删除',
      content: `确定要删除数据集「${name}」及其所有镜像记录吗？此操作不可恢复。`,
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          await deleteDataset(id);
          message.success('数据集已删除');
          fetchDatasets();
        } catch (err: any) {
          message.error(err?.response?.data?.detail || '删除失败');
        }
      },
    });
  };

  const columns = [
    {
      title: '数据集名称',
      dataIndex: 'name',
      key: 'name',
      render: (text: string, record: DatasetSummary) => (
        <a onClick={() => navigate(`/datasets/${record.id}`)}>{text}</a>
      ),
    },
    {
      title: 'Agent',
      key: 'agent',
      width: 160,
      render: (_: unknown, record: DatasetSummary) =>
        record.agent
          ? record.agent_version
            ? `${record.agent} / ${record.agent_version}`
            : record.agent
          : '-',
    },
    {
      title: '镜像数量',
      dataIndex: 'image_count',
      key: 'image_count',
      width: 120,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 200,
      render: (t: string) => t ? new Date(t).toLocaleString() : '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 80,
      render: (_: unknown, record: DatasetSummary) => (
        <Button
          type="link"
          danger
          icon={<DeleteOutlined />}
          size="small"
          onClick={(e) => {
            e.stopPropagation();
            handleDeleteDataset(record.id, record.name);
          }}
        >
          删除
        </Button>
      ),
    },
  ];

  return (
    <Card
      className="glass-card"
      title="数据集列表"
      extra={
        <Space>
          <Search
            placeholder="搜索数据集名称"
            onSearch={handleSearch}
            allowClear
            style={{ width: 250 }}
          />
          <Button icon={<ReloadOutlined />} onClick={() => fetchDatasets()} loading={loading}>
            刷新
          </Button>
        </Space>
      }
    >
      <Button
        icon={<ArrowLeftOutlined />}
        onClick={() => navigate('/')}
        style={{ marginBottom: 16 }}
      >
        返回首页
      </Button>
      <Table
        dataSource={datasets}
        columns={columns}
        rowKey="id"
        loading={loading}
        pagination={false}
        onRow={(record) => ({
          onClick: () => navigate(`/datasets/${record.id}`),
          style: { cursor: 'pointer' },
        })}
      />
    </Card>
  );
}
