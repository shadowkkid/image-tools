# envd 镜像构建流程

## 什么是 envd

envd 是一个二进制守护进程（e2b infra daemon），运行时监听端口 49983，用于 Terminus-2 沙箱平台的基础设施管理。它**不是**构建工具，而是注入到 Docker 镜像中的运行时组件，使镜像兼容 e2b/Terminus 基础设施。

二进制路径配置在 `backend/config.py`，当前指向：
`/home/SENSETIME/lizimu/workspace/python/testTerminus/envd`

---

## 构建模式概览

系统支持三种构建模式，由 `agent` 配置决定：

| 模式 | Agent | 说明 | 阶段数 |
|------|-------|------|--------|
| `build` | OpenHands | 完整 Dockerfile 构建 | 4 |
| `retag` | mini-swe-agent | 拉取-重标签-推送 | 3 |
| **`harbor`** | harbor (terminus2) | **envd 注入构建** | 4 |

---

## envd/Harbor 构建流程 Graph

```
┌─────────────────────────────────────────────────────────────┐
│                    用户创建任务                                │
│  POST /api/tasks                                            │
│  agent="harbor", agent_version="terminus2"                  │
│  dataset_path="..." (本地路径 或 dataset@version)            │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              Agent 配置解析 (config.py)                      │
│  get_agent_config("harbor", "terminus2")                    │
│  → build_mode = "harbor"                                    │
│  → envd_binary_path = "/.../envd"                           │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│         Harbor 数据集解析 (harbor_dataset_parser.py)          │
│                                                             │
│  dataset_path 是引用格式 (name@version)?                     │
│  ├─ 是 → harbor CLI 下载到 ~/.cache/harbor/...              │
│  └─ 否 → 直接使用本地路径                                    │
│                                                             │
│  遍历子目录，解析每个 task.toml:                              │
│  ├─ 读取 [environment].docker_image (优先)                   │
│  └─ 或读取 environment/Dockerfile 的 FROM 行 (兜底)          │
│                                                             │
│  输出: List[HarborTaskInfo]                                  │
│        (task_name, docker_image, dockerfile_path, base_image)│
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│         创建 BuildTask (task_manager.py)                     │
│                                                             │
│  为每个 HarborTaskInfo 创建 ImageBuildInfo:                   │
│  ├─ stage_names = HARBOR_STAGES                             │
│  │   [docker_build_original, docker_build_envd,             │
│  │    docker_tag, docker_push]                              │
│  ├─ template_name = {task_name}__{sha256(base)[:8]}         │
│  └─ harbor_task_name, harbor_dockerfile_path 等字段          │
│                                                             │
│  保存到 SQLite → 启动 asyncio 后台执行                        │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│      并发执行 (asyncio.Semaphore, 默认 concurrency=2)        │
│      每个镜像走 _execute_harbor_pipeline                     │
└──────────────────────────┬──────────────────────────────────┘
                           │
            ┌──────────────┴──────────────┐
            ▼                             ▼
   ┌─── Image A ───┐            ┌─── Image B ───┐
   │  (并行构建)    │            │  (并行构建)    │
   └───────┬───────┘            └───────┬───────┘
           │                            │
           ▼                            ▼
╔═════════════════════════════════════════════════════════════╗
║              单个镜像的 4 阶段 Pipeline                      ║
║                                                             ║
║  ┌─────────────────────────────────────────────────────┐    ║
║  │ Stage 1: docker_build_original                      │    ║
║  │                                                     │    ║
║  │  三选一:                                            │    ║
║  │  ├─ harbor_docker_image 存在?                       │    ║
║  │  │  → docker pull {harbor_docker_image}             │    ║
║  │  ├─ harbor_dockerfile_path 存在?                    │    ║
║  │  │  → docker build -f {dockerfile_path} .           │    ║
║  │  └─ 兜底:                                           │    ║
║  │     → docker pull {base_image}                      │    ║
║  │                                                     │    ║
║  │  Tag → image-tools-harbor/{safe_name}:original      │    ║
║  └──────────────────────┬──────────────────────────────┘    ║
║                         │                                    ║
║                         ▼                                    ║
║  ┌─────────────────────────────────────────────────────┐    ║
║  │ Stage 2: docker_build_envd (核心阶段)                │    ║
║  │                                                     │    ║
║  │  1. 创建临时构建目录 (tempfile.mkdtemp)              │    ║
║  │  2. 复制 envd 二进制到临时目录                        │    ║
║  │  3. 生成 entrypoint.sh:                             │    ║
║  │     ┌──────────────────────────────────┐            │    ║
║  │     │ #!/bin/bash                      │            │    ║
║  │     │ envd -port 49983 -isnotfc &      │            │    ║
║  │     │ exec "${@:-bash}"                │            │    ║
║  │     └──────────────────────────────────┘            │    ║
║  │  4. 渲染 Dockerfile.envd.j2 模板:                   │    ║
║  │     ┌──────────────────────────────────┐            │    ║
║  │     │ FROM {original_image}            │            │    ║
║  │     │ RUN apt-get install -y           │            │    ║
║  │     │     tmux asciinema bsdutils      │            │    ║
║  │     │ COPY envd /usr/local/bin/envd    │            │    ║
║  │     │ RUN chmod +x envd               │            │    ║
║  │     │ EXPOSE 49983                     │            │    ║
║  │     │ # sleep 包装 (k8s 兼容)          │            │    ║
║  │     │ RUN mv sleep → sleep.real        │            │    ║
║  │     │     创建 sleep 包装脚本           │            │    ║
║  │     │     (自动启动 envd 后执行原 sleep)│            │    ║
║  │     │ COPY entrypoint.sh               │            │    ║
║  │     │ ENTRYPOINT ["/entrypoint.sh"]    │            │    ║
║  │     └──────────────────────────────────┘            │    ║
║  │  5. docker build → envd 注入镜像                     │    ║
║  │                                                     │    ║
║  │  Tag → image-tools-harbor/{safe_name}:envd          │    ║
║  └──────────────────────┬──────────────────────────────┘    ║
║                         │                                    ║
║                         ▼                                    ║
║  ┌─────────────────────────────────────────────────────┐    ║
║  │ Stage 3: docker_tag                                 │    ║
║  │  Tag envd 镜像 → {push_dir}/{image_path}:{tag}     │    ║
║  └──────────────────────┬──────────────────────────────┘    ║
║                         │                                    ║
║                         ▼                                    ║
║  ┌─────────────────────────────────────────────────────┐    ║
║  │ Stage 4: docker_push                                │    ║
║  │  推送到远程 Registry                                 │    ║
║  └──────────────────────┬──────────────────────────────┘    ║
║                         │                                    ║
║                         ▼                                    ║
║  ┌─────────────────────────────────────────────────────┐    ║
║  │ Cleanup                                             │    ║
║  │  ├─ 删除临时构建目录                                 │    ║
║  │  ├─ 删除本地中间镜像 (original, envd, target)        │    ║
║  │  └─ 清理 BuildKit 构建缓存                           │    ║
║  └─────────────────────────────────────────────────────┘    ║
╚═════════════════════════════════════════════════════════════╝
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                   任务状态汇总                                │
│  所有镜像成功 → COMPLETED                                    │
│  部分失败     → PARTIAL_FAILED                               │
│  全部失败     → FAILED                                       │
│  (失败时支持重试, 最多 retry_count + 1 次)                    │
└─────────────────────────────────────────────────────────────┘
```

---

## envd 注入的两种激活方式

### 1. Kubernetes 模式 (sleep 包装)

当 k8s Pod spec 使用 `command: [sleep, inf]` 启动容器时：

```
/usr/bin/sleep (包装脚本)
  ├─ 检测 envd 是否已运行 (pgrep -x envd)
  ├─ 未运行 → 启动 envd -port 49983 -isnotfc &
  └─ exec /usr/bin/sleep.real "$@"
```

这是一个透明激活机制——无需修改 k8s 配置，envd 自动随容器启动。

### 2. Docker Run 模式 (entrypoint)

直接 `docker run` 时使用 entrypoint.sh：

```
/entrypoint.sh
  ├─ envd -port 49983 -isnotfc &
  └─ exec "${@:-bash}"
```

---

## 关键文件索引

| 文件 | 职责 |
|------|------|
| `backend/config.py` | Agent 配置，含 envd_binary_path |
| `backend/api/tasks.py` | 任务创建 API 入口 |
| `backend/api/schemas.py` | 请求/响应数据模型 |
| `backend/core/task_manager.py` | 任务编排：创建、执行、重试、取消 |
| `backend/core/task_models.py` | 数据模型：BuildTask, ImageBuildInfo, HARBOR_STAGES |
| `backend/core/docker_service.py` | Docker CLI 异步封装 (build/pull/tag/push/prune) |
| `backend/core/database.py` | SQLite 持久化，含 harbor 字段迁移 |
| `backend/builder/dockerfile_generator.py` | Jinja2 模板渲染 |
| `backend/builder/image_builder.py` | 核心构建逻辑，含 `_execute_harbor_pipeline` |
| `backend/builder/harbor_dataset_parser.py` | 数据集解析 (task.toml + Dockerfile) |
| `backend/templates/Dockerfile.envd.j2` | envd 注入层 Dockerfile 模板 |
| `frontend/src/pages/TaskDetail.tsx` | 前端阶段展示 ("注入 envd 层") |

---

## 数据库 Schema (harbor 相关)

**tasks 表**：
- `envd_binary_path` — envd 二进制路径

**images 表**：
- `harbor_task_name` — harbor 数据集中的任务名
- `harbor_dockerfile_path` — 任务自带的 Dockerfile 路径
- `harbor_docker_image` — 任务指定的预构建镜像

数据库启动时自动迁移添加这些列（`database.py` L131-144）。
