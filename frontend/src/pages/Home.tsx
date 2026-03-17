import { useNavigate } from 'react-router-dom';
import { Card, Space } from 'antd';
import { RocketOutlined, DatabaseOutlined } from '@ant-design/icons';

export default function Home() {
  const navigate = useNavigate();

  return (
    <div style={{ maxWidth: 640, margin: '80px auto 0' }}>
      <h2 style={{ textAlign: 'center', marginBottom: 40, color: '#F5F5F5', fontWeight: 600 }}>
        Image Tools
      </h2>
      <Space direction="vertical" size={20} style={{ width: '100%' }}>
        <Card
          className="glass-card home-entry-card"
          hoverable
          onClick={() => navigate('/tasks')}
        >
          <Space size={16} align="center">
            <RocketOutlined style={{ fontSize: 32, color: '#7C5CFC' }} />
            <div>
              <div style={{ fontSize: 16, fontWeight: 600, color: '#F5F5F5' }}>
                任务管理
              </div>
              <div style={{ color: '#888', marginTop: 4 }}>
                创建、查看和管理镜像构建任务
              </div>
            </div>
          </Space>
        </Card>

        <Card
          className="glass-card home-entry-card"
          hoverable
          onClick={() => navigate('/datasets')}
        >
          <Space size={16} align="center">
            <DatabaseOutlined style={{ fontSize: 32, color: '#5BA0F6' }} />
            <div>
              <div style={{ fontSize: 16, fontWeight: 600, color: '#F5F5F5' }}>
                数据集管理
              </div>
              <div style={{ color: '#888', marginTop: 4 }}>
                按数据集查看已构建的镜像
              </div>
            </div>
          </Space>
        </Card>
      </Space>
    </div>
  );
}
