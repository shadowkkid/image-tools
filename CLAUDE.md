# Image Tools

基于 OpenHands_Ss 优化的 deps_image 方案，提供镜像批量构建和推送的 Web 管理工具。

## 技术栈

- **后端**: Python 3.14 + FastAPI + uvicorn + Jinja2 + Pydantic
- **前端**: Vite + React 19 + TypeScript + Ant Design 5 + axios + react-router-dom
- **构建模板**: 从 OpenHands_Ss 的 Dockerfile.deps.j2 复制，使用 deps_image 多阶段构建加速

## 项目结构

```
backend/          # FastAPI 后端
  api/            # API 路由 (registry.py, tasks.py, schemas.py)
  core/           # 核心模块 (docker_service, task_manager, task_models)
  builder/        # 构建模块 (dockerfile_generator, image_builder)
  templates/      # Dockerfile Jinja2 模板
frontend/         # React 前端
  src/pages/      # 页面 (TaskCreate, TaskList, TaskDetail)
  src/components/ # 组件 (LoginModal)
  src/api/        # API 客户端
tests/            # pytest 测试
```

## 启动方式

```bash
# 后端 (端口 8000)
cd image-tools && python -m backend.main

# 前端开发 (端口 3000, 代理 /api -> localhost:8000)
cd frontend && npm run dev

# 前端构建 (生成 frontend/dist, 后端自动 serve)
cd frontend && npm run build
```

## 关联项目

- OpenHands_Ss 源码: `/home/SENSETIME/lizimu/workspace/python/OpenHands_Ss`

---

# 开发规范

## 语言

使用中文与用户沟通。commit message 使用中文。代码中的变量名、函数名、注释使用英文。

## 开发流程

每次接到需求，严格按以下顺序执行：

1. **理解需求** — 先阅读相关代码，理解现有架构和上下文，再动手。不要在没读过代码的情况下提出修改方案。
2. **方案确认** — 对于涉及多文件或架构决策的改动，先说明方案思路，经用户确认后再实现。简单改动可直接执行。
3. **实现** — 遵循项目已有的代码风格和最佳实践，保持结构清晰、命名规范、职责单一。
4. **测试** — 改动完成后必须验证：
   - 先跑单元测试，确保不破坏已有功能
   - 再跑全链路/集成测试，验证端到端行为正确
   - 测试不通过则修复后重新验证，直到全部通过
5. **提交并推送** — 端到端测试全部通过后，自动提交 commit 并 push，无需等待用户确认。

## 测试要求

- 新增功能必须补充对应的单元测试
- 修改已有逻辑时，更新受影响的测试用例
- **不要只跑单元测试就认为完成**，必须跑全链路测试验证实际效果
- 测试命令和跳过条件需要根据项目实际情况判断，不要盲目跳过失败的测试

## Commit 规范

- 格式：`type(scope): 简短描述`，如 `feat(runtime-build): 支持从预构建依赖镜像加速构建`
- type 常用值：feat / fix / refactor / chore / test / docs
- commit message body 必须包含以下内容（中文），确保后期可追溯：
  - **需求**：本次改动对应的需求是什么
  - **思路**：采用了什么方案、为什么这样做
  - **改动点**：改了哪些文件、每个文件改了什么
  - **验证**：跑了哪些测试、结果如何
- 一个 commit 对应一个完整的需求或修复，不要把不相关的改动混在一起

## 代码最佳实践

- 遵循项目已有的代码风格和目录结构，保持一致性
- 函数职责单一，命名清晰表达意图
- 优先复用已有代码和模式，避免重复实现
- 不引入不必要的抽象和封装，不添加"以防万一"的错误处理
- 改动前先确认影响范围，避免意外破坏其他功能
- 新增文件时放在合理的目录位置，遵循现有模块划分

## 环境问题处理

遇到环境问题（缺少语言运行时、工具、依赖等）时，优先自行解决，不要反复询问用户：

1. **优先使用 mise** 安装语言和工具（如 python、node、go 等）
   - 如果环境中没有 mise，先安装 mise 并配置好再继续
   - 安装命令：`curl https://mise.run | sh`，然后 `eval "$(~/.local/bin/mise activate bash)"`
2. **mise 不支持或不适用时**，再考虑其他方式（pip、npm、apt 等）
3. 安装完成后验证可用性，确认无误再继续开发任务