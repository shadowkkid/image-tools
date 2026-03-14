import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ConfigProvider, Layout, Typography } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import TaskCreate from './pages/TaskCreate';
import TaskList from './pages/TaskList';
import TaskDetail from './pages/TaskDetail';

const { Header, Content } = Layout;

export default function App() {
  return (
    <ConfigProvider locale={zhCN}>
      <BrowserRouter>
        <Layout style={{ minHeight: '100vh' }}>
          <Header
            style={{
              display: 'flex',
              alignItems: 'center',
              background: '#001529',
              padding: '0 24px',
            }}
          >
            <Typography.Title
              level={4}
              style={{ color: '#fff', margin: 0, cursor: 'pointer' }}
              onClick={() => (window.location.href = '/tasks')}
            >
              Image Tools
            </Typography.Title>
          </Header>
          <Content style={{ padding: 24, background: '#f5f5f5' }}>
            <Routes>
              <Route path="/" element={<Navigate to="/tasks" replace />} />
              <Route path="/tasks" element={<TaskList />} />
              <Route path="/create" element={<TaskCreate />} />
              <Route path="/tasks/:taskId" element={<TaskDetail />} />
            </Routes>
          </Content>
        </Layout>
      </BrowserRouter>
    </ConfigProvider>
  );
}
