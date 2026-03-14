# Image Tools

基于 OpenHands 优化的 deps_image 方案，提供镜像批量构建和推送的 Web 管理工具。

通过 Dockerfile 模板 + 多阶段构建，将预构建的依赖镜像与不同 base 镜像组合，快速生成多个 runtime 镜像并推送到指定 registry。

## 架构

```
┌──────────────┐       ┌──────────────┐
│   React SPA  │──────▶│  FastAPI API  │──────▶ Docker Engine
│  (Ant Design)│  /api │  (uvicorn)   │        (build/tag/push)
└──────────────┘       └──────────────┘
                              │
                              ▼
                        SQLite (tasks.db)
```

- **前端**: Vite + React 19 + TypeScript + Ant Design 5
- **后端**: Python 3.14 + FastAPI + uvicorn + Jinja2
- **持久化**: SQLite（自动创建 `tasks.db`）
- **构建**: Docker 多阶段构建，Jinja2 模板生成 Dockerfile

## 目录结构

```
backend/
  api/            # API 路由 (registry, tasks) 和请求/响应 schema
  core/           # 核心模块 (task_manager, task_models, database, docker_service)
  builder/        # 构建模块 (dockerfile_generator, image_builder)
  templates/      # Dockerfile Jinja2 模板
frontend/
  src/pages/      # 页面 (TaskCreate, TaskList, TaskDetail)
  src/components/ # 组件 (LoginModal)
  src/api/        # API 客户端
tests/            # pytest 测试
```

## 环境要求

- Python 3.12+
- Node.js 18+
- Docker（需要本地 Docker daemon 运行）

## 配置项

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| `IMAGE_TOOLS_SOURCE_DIR` | OpenHands 源码目录路径 | `/home/SENSETIME/lizimu/workspace/python/OpenHands_Ss` |

## 启动方式

### 开发模式

```bash
# 后端（端口 8000）
cd image-tools && python -m backend.main

# 前端开发服务器（端口 3000，代理 /api → localhost:8000）
cd frontend && npm run dev
```

### 生产模式

```bash
# 构建前端静态资源
cd frontend && npm run build

# 启动后端（自动 serve frontend/dist）
cd image-tools && python -m backend.main
```

## API 概览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/registry/check-auth` | 检查 registry 认证状态 |
| POST | `/api/registry/login` | Docker registry 登录 |
| POST | `/api/tasks` | 创建构建任务 |
| GET  | `/api/tasks` | 获取任务列表 |
| GET  | `/api/tasks/{task_id}` | 获取任务详情 |
| POST | `/api/tasks/{task_id}/stop` | 停止运行中的任务 |

## 测试

```bash
python -m pytest tests/ -v
```
