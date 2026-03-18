import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Card, Table, Input, Button, Space, Modal, message } from 'antd';
import { ArrowLeftOutlined, ReloadOutlined, DeleteOutlined } from '@ant-design/icons';
import { getDatasetImages, batchDeleteDatasetImages } from '../api/client';
import type { DatasetImageItem } from '../types';

const { Search } = Input;

export default function DatasetDetail() {
  const { datasetId } = useParams<{ datasetId: string }>();
  const navigate = useNavigate();
  const [images, setImages] = useState<DatasetImageItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const pageSize = 50;

  const fetchImages = async (p: number = page, q: string = search) => {
    if (!datasetId) return;
    setLoading(true);
    try {
      const res = await getDatasetImages(Number(datasetId), {
        search: q,
        page: p,
        page_size: pageSize,
      });
      setImages(res.images);
      setTotal(res.total);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchImages(1);
  }, [datasetId]);

  const handleSearch = (value: string) => {
    setSearch(value);
    setPage(1);
    fetchImages(1, value);
  };

  const handlePageChange = (newPage: number) => {
    setPage(newPage);
    fetchImages(newPage);
  };

  const handleBatchDelete = () => {
    if (selectedRowKeys.length === 0) return;
    Modal.confirm({
      title: '确认删除',
      content: `确定要删除选中的 ${selectedRowKeys.length} 条镜像记录吗？此操作不可恢复。`,
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          await batchDeleteDatasetImages(Number(datasetId), selectedRowKeys.map(Number));
          message.success('镜像记录已删除');
          setSelectedRowKeys([]);
          fetchImages();
        } catch (err: any) {
          message.error(err?.response?.data?.detail || '删除失败');
        }
      },
    });
  };

  const columns = [
    {
      title: '镜像名称',
      dataIndex: 'image_name',
      key: 'image_name',
      ellipsis: true,
      render: (text: string) => <code>{text}</code>,
    },
    {
      title: '来源任务',
      dataIndex: 'task_name',
      key: 'task_name',
      width: 200,
      render: (text: string, record: DatasetImageItem) => (
        <a onClick={(e) => { e.stopPropagation(); navigate(`/tasks/${record.task_id}`); }}>
          {text}
        </a>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 200,
      render: (t: string) => t ? new Date(t).toLocaleString() : '-',
    },
  ];

  return (
    <Card
      className="glass-card"
      title="数据集镜像列表"
      extra={
        <Space>
          {selectedRowKeys.length > 0 && (
            <Button
              danger
              icon={<DeleteOutlined />}
              onClick={handleBatchDelete}
            >
              删除选中 ({selectedRowKeys.length})
            </Button>
          )}
          <Search
            placeholder="搜索镜像名称"
            onSearch={handleSearch}
            allowClear
            style={{ width: 300 }}
          />
          <Button icon={<ReloadOutlined />} onClick={() => fetchImages()} loading={loading}>
            刷新
          </Button>
        </Space>
      }
    >
      <Button
        icon={<ArrowLeftOutlined />}
        onClick={() => navigate('/datasets')}
        style={{ marginBottom: 16 }}
      >
        返回数据集列表
      </Button>
      <Table
        dataSource={images}
        columns={columns}
        rowKey="id"
        loading={loading}
        rowSelection={{
          selectedRowKeys,
          onChange: (keys) => setSelectedRowKeys(keys),
        }}
        pagination={{
          current: page,
          pageSize,
          total,
          onChange: handlePageChange,
          showTotal: (t) => `共 ${t} 条`,
          showSizeChanger: false,
        }}
      />
    </Card>
  );
}
