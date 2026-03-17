import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { ConfigProvider, Layout, theme } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import Home from './pages/Home';
import TaskCreate from './pages/TaskCreate';
import TaskList from './pages/TaskList';
import TaskDetail from './pages/TaskDetail';
import DatasetList from './pages/DatasetList';
import DatasetDetail from './pages/DatasetDetail';
import './App.css';

const { Content } = Layout;

const darkTheme = {
  algorithm: theme.darkAlgorithm,
  token: {
    colorPrimary: '#7C5CFC',
    colorBgBase: '#0D0D0D',
    colorTextBase: '#E8E8E8',
    colorBgContainer: 'rgba(255,255,255,0.03)',
    colorBgElevated: '#1A1A1A',
    colorBorder: 'rgba(255,255,255,0.08)',
    colorBorderSecondary: 'rgba(255,255,255,0.06)',
    colorText: '#E8E8E8',
    colorTextSecondary: '#888888',
    colorTextTertiary: '#666666',
    colorTextHeading: '#F5F5F5',
    colorSuccess: '#3DD68C',
    colorWarning: '#F0B449',
    colorError: '#EF6461',
    colorLink: '#7C5CFC',
    colorLinkHover: '#9B82FC',
    borderRadius: 10,
    fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
  },
  components: {
    Layout: {
      bodyBg: '#0D0D0D',
      headerBg: 'transparent',
      headerHeight: 56,
      headerPadding: '0 24px',
    },
    Card: {
      colorBgContainer: 'rgba(255,255,255,0.03)',
      colorBorderSecondary: 'rgba(255,255,255,0.06)',
    },
    Table: {
      colorBgContainer: 'transparent',
      headerBg: 'rgba(255,255,255,0.03)',
      headerColor: '#888888',
      rowHoverBg: 'rgba(255,255,255,0.06)',
      borderColor: 'rgba(255,255,255,0.06)',
    },
    Modal: {
      contentBg: '#1A1A1A',
      headerBg: '#1A1A1A',
      titleColor: '#F5F5F5',
    },
    Descriptions: {
      colorSplit: 'rgba(255,255,255,0.06)',
      labelBg: 'rgba(255,255,255,0.03)',
    },
    Input: {
      colorBgContainer: 'rgba(255,255,255,0.04)',
      activeBorderColor: '#7C5CFC',
      hoverBorderColor: 'rgba(124,92,252,0.5)',
    },
    InputNumber: {
      colorBgContainer: 'rgba(255,255,255,0.04)',
      activeBorderColor: '#7C5CFC',
      hoverBorderColor: 'rgba(124,92,252,0.5)',
    },
    Button: {
      primaryShadow: 'none',
      defaultBg: 'rgba(255,255,255,0.06)',
      defaultBorderColor: 'rgba(255,255,255,0.10)',
    },
    Tag: {
      defaultBg: 'rgba(255,255,255,0.06)',
      defaultColor: '#E8E8E8',
    },
  },
};

export default function App() {
  return (
    <ConfigProvider locale={zhCN} theme={darkTheme}>
      <BrowserRouter>
        <Layout style={{ minHeight: '100vh', background: '#0D0D0D' }}>
          <header className="app-header">
            <span
              className="header-title"
              onClick={() => (window.location.href = '/')}
            >
              Image Tools
            </span>
          </header>
          <Content className="app-content">
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/tasks" element={<TaskList />} />
              <Route path="/create" element={<TaskCreate />} />
              <Route path="/tasks/:taskId" element={<TaskDetail />} />
              <Route path="/datasets" element={<DatasetList />} />
              <Route path="/datasets/:datasetId" element={<DatasetDetail />} />
            </Routes>
          </Content>
        </Layout>
      </BrowserRouter>
    </ConfigProvider>
  );
}
