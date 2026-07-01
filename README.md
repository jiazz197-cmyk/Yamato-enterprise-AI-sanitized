<div align="center">

# Yamato AI 助手平台

### 大和计量设备（上海）智能工作台

<p align="center">
  <a href="#简介">简介</a> •
  <a href="#核心能力">核心能力</a> •
  <a href="#架构概览">架构概览</a> •
  <a href="#前端页面">前端页面</a> •
  <a href="#api-访问">API 访问</a> •
  <a href="#仓库结构速览">仓库结构</a>
</p>

![Python Version](https://img.shields.io/badge/python-3.12+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.116.1-009688.svg)
![Vue](https://img.shields.io/badge/Vue-3-4FC08D.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

</div>

---

## 简介

Yamato AI 助手平台是专为**大和衡器（上海）**打造的企业内部 AI 工作平台。员工通过自然语言对话访问企业知识库、智能处理各类文档、生成报价、填写设备订单报单，大幅减少重复性信息查找与手动录入工作。

平台采用 FastAPI（Python 3.12）后端 + Vue 3（pnpm / Turbo monorepo）前端，遵循 **Route → UseCase → Port → Adapter** 的分层架构，核心 AI 能力（RAG 检索、对话工作流、报价流水线）均在进程内编排，不依赖外部编排引擎。

---

## 核心能力

### AI 知识库对话

员工直接用自然语言提问，AI 基于企业内部文档给出有依据的精准回答。对话工作流以 **langchain** 为底座运行在 yamato 进程内，三路检索按需切换：

- **本地检索**：基于已上传企业文档的 RAG 检索（表单数据 + 离散知识双实例）
- **联网搜索**：补充外部信息（默认 Tavily 后端）
- **本地 & 网络**：混合检索，本地结果与网络结果合并作答
- 双层记忆：长期摘要记忆 + 近期原始对话，支持用 `background` 覆盖重置
- 关键词拆分 / 意图增强（Qwen3-8B）→ 流式答案（Qwen3.6-35B-A3B，`<think>` 推理段实时剥离）
- 对话历史与会话/消息持久化，支持重命名与分页回看
- 协作式取消：客户端可随时停止当前回答流

### 智能文档处理

上传企业文档后，系统自动解析内容并建立可检索的知识库，无需人工标注或整理。

- 支持格式：PDF、Word（.docx）、Excel（.xlsx）、PowerPoint（.pptx）、HTML、纯文本
- 上传即处理，实时显示处理进度
- 处理完成后文档内容立即可被 AI 对话检索引用

### 报价生成（PDF 图纸流水线）

侧边栏 **「报价生成」**（路由 `/files`）上传 **PDF 图纸**，走两阶段异步流水线；任务进度支持 **WebSocket** 推送（并保留轮询兜底）。

- **Phase1**：PDF 首页栅格化 → OCR → 关键词映射 → PDM BOM 查询，进入**等待审核**
- **Phase2**：用户勾选保留的 PARTID 后触发 U8 BOM + 库存查询，按类型汇总
- 阶段产物存入 MinIO；Phase2 结束后生成 **按类型多 Sheet 的 xlsx**（`quotation-results/{task_id}/u8_by_type.xlsx`）
- 完成后可 **鉴权下载** 原始处理 PDF 与 **U8 分组 Excel**
- 全程支持协作式取消；服务重启后中断任务自动重排队

> 知识库文档的上传与处理进度在 **AI 对话页** 内完成；集合与文档管理在 **知识库管理页**（`/collection2`）。请勿与报价任务的 PDF 混淆。

### OCR 图像识别

将扫描件、拍照图片或 PDF 中的文字自动识别并提取为结构化文本。

- 支持中英文混合识别、表格结构识别
- 支持将 PDF 逐页转换为图片，便于预览和 OCR 处理

### 报单智能填写

专为**大和智能组合秤产品**设计的订单填报页面，结构化收集订单参数，替代手工录表。

- 填报字段：客户名称、产品类型与型号、计量规格、机械结构参数、秤体类型、数量与价格
- 提交后自动归档，可随时查询历史记录
- 历史报单内容支持语义检索

### 对话记录归档

平台自动分析用户历史对话，提炼问询习惯与偏好，生成**用户画像摘要**；并在长对话上下文超长时做自动压缩，保持检索与作答质量。

---

## 架构概览

### 分层架构（Route → UseCase → Port → Adapter）

依赖方向：内层稳定，外层易变。路由层是**组合根**，负责构造 Adapter 并注入 UseCase；UseCase 只认 Port 类型，从不触碰集成实现。该约束由 `scripts/check_layered_architecture.sh` 强制校验（CI 唯一检查项）。

| 层 | 位置 | 职责 | 禁止 |
|----|------|------|------|
| **Route** | `app/api/v1/` | 解析/校验输入、构造 Adapter + UseCase、映射 HTTP 响应 | （修复路由）直接 import `app.integrations` |
| **UseCase** | `app/usecases/` | 编排业务步骤，接收 Port，返回稳定结果 | import `app.integrations`、ORM、HTTP 客户端 |
| **Port** | `app/ports/` | `Protocol` 契约 + 纯 DTO | 做 IO |
| **Adapter** | `app/adapters/` | 实现 Port，桥接到集成层/ORM/配置 | 容纳完整业务流程（留在 UseCase） |
| **Domain** | `app/domain/` | 无 IO 纯函数 + 共享异常 | — |
| **Integration** | `app/integrations/` | 第三方 / HTTP / SQL 实现细节 | 被 UseCase 或修复路由 import |

### 对话工作流（langchain，进程内）

- **Route** `app/api/v1/conversation.py`：Dify 兼容 SSE 端点（`/chat-messages`、`/conversations`、`/messages`、重命名），JWT 鉴权，内存态协作式取消
- **UseCase** `app/usecases/conversation/run.py`：编排会话解析 → 记忆覆盖 → 用户画像 → 双通记忆装配 → 流式作答 → 持久化
- **Integration** `app/integrations/conversation/pipeline.py`：三路分支应答引擎（关键词提取 → 本地检索 / 联网搜索 → 意图增强 → 流式答案，`<think>` 实时剥离）
- **Runtime** `app/integrations/conversation/runtime.py`：进程级 LLM 客户端单例（连接池复用）+ 按模型分桶信号量（8B=20 / 35B=10，请求级背压）+ 专用检索线程池（隔离阻塞式 RAG，max=8）
- **Storage** `app/models/orm/conversation.py`：`conversations`（持有 `long_memory` + `recent_dialogs`）与 `messages` 行；`ConversationRepoPort` 为唯一真相源，被对话、聊天摘要、上下文压缩共用

### 报价生成流水线

两阶段状态机：`queued` → `running`(Phase1) → `awaiting_approval` → `running`(Phase2) → `completed`（另有 `failed` / `cancelled`）。PostgreSQL 为状态真相源，Redis 为 WS 进度缓存镜像；协程式取消贯穿 Port 调用。详见 `docs/quotation-task-and-data-flow.md`、`docs/task-state-truth.md`。

### 任务基础设施

所有异步任务共享：Redis 任务状态管理（观察者模式）+ 线程池执行器 + WebSocket 进度推送 + 按用户队列调度 + 留存策略（总量 > 100 裁剪至 ≤ 50；等待审核超 24h 清理）。

---

## 前端页面

前端 Monorepo 主应用为 [`frontend/apps/chat`](frontend/apps/chat)。登录后可使用核心业务页面；另有注册页与按角色开放的管理页：

| 页面 | 路径 | 访问说明 |
|------|------|----------|
| 登录页 | `/login` | 公开；已登录访问将跳转对话页 |
| 注册页 | `/register` | 公开；已登录访问将跳转对话页 |
| AI 对话页 | `/chat` | 需登录；侧边栏含知识库文档上传入口 |
| 报价生成页 | `/files` | 需登录；PDF 报价任务、PDM 审核、U8、下载 PDF / Excel |
| 报单填写页 | `/closing-form` | 需登录；填写并提交智能组合秤订单报单 |
| 用户管理页 | `/users` | 需登录且角色为 **superuser** |
| 知识库管理页 | `/collection2` | 需登录且角色为 **admin** 或 **superuser** |

> 未登录用户访问除 `/login`、`/register` 外的路由将跳转至登录页。无相应角色访问管理页时将被重定向至对话页。

---

## API 访问

后端服务启动后，可通过以下地址访问：

| 服务 | 地址 |
|------|------|
| 主服务 | http://localhost:8000 |
| Swagger UI（交互式 API 文档） | http://localhost:8000/api/v1/docs |
| ReDoc（API 参考文档） | http://localhost:8000/api/v1/redoc |
| 健康检查 | http://localhost:8000/api/v1/health |

API 统一前缀 `/api/v1`。报价相关接口前缀 `/api/v1/quotation`，OpenAPI 标签为 **Quotation Generation**；对话接口为 Dify 兼容形态的 `/api/v1/chat-messages` 等。生产环境关闭文档与 OpenAPI，`/metrics` 受 API Key 保护。

---

## 仓库结构速览

| 路径 | 说明 |
|------|------|
| [`main.py`](main.py) | FastAPI 入口、生命周期（报价队列恢复、SQL Server 连通性检查、依赖降级初始化） |
| [`app/api/v1/`](app/api/v1/) | 路由层（组合根），`registry.py` 扁平装配各业务 router |
| [`app/usecases/`](app/usecases/) | 业务用例编排（对话、报价、聊天摘要、上下文压缩等） |
| [`app/ports/`](app/ports/) | `Protocol` 契约（`contracts/`、`domains/`）+ 纯 DTO（`dto/`） |
| [`app/adapters/`](app/adapters/) | Port 实现，桥接 ORM / 集成层 / 配置 |
| [`app/domain/`](app/domain/) | 无 IO 纯函数（记忆拼装、`<think>` 剥离、搜索筛选、提示词等）与共享异常 |
| [`app/integrations/`](app/integrations/) | 第三方/HTTP/SQL 实现（对话 langchain 管线、报价、OCR、RAG 等） |
| [`app/models/orm/`](app/models/orm/) | SQLAlchemy ORM（对话、消息、报价任务等） |
| [`app/core/`](app/core/) | 配置、任务管理器、执行器、WS、中间件、安全、仓储 |
| [`frontend/`](frontend/) | pnpm + Turbo Monorepo；业务应用在 [`frontend/apps/chat`](frontend/apps/chat) |
| [`tests/`](tests/) | 单元/回归测试；`tests/scripts/full_acceptance_regression.sh` 端到端冒烟 |
| [`scripts/`](scripts/) | 启动脚本、nginx 渲染、分层架构 guard |
| [`docs/`](docs/) | 架构与子系统文档（分层模式、报价流水线、对话工作流、任务状态真相等） |

---

## 更新日志

### v1.0.1（2026-06）

- **对话工作流**：从 Dify 全面迁移至进程内 **langchain** 实现，弃用 Dify；三路检索 + 双层记忆 + 流式答案，`<think>` 实时剥离
- **并发模型**：LLM 客户端单例化（连接池复用）+ 按模型分桶信号量背压 + 专用 RAG 检索线程池
- **存储**：新增 `conversations` / `messages` 本地表，`ConversationRepoPort` 成为会话/消息/记忆唯一真相源
- **联动改造**：聊天摘要、上下文压缩改读本地存储，脱离 Dify HTTP
- **清理**：移除 Dify nginx 反代 / 探活 / 配置项 / 前端环境变量 / 原 yml 工作流文件

### v0.2.2（2026-04）

- **报价生成**：Phase2 完成后生成 U8 按类型多 Sheet **Excel**，上传 MinIO
- **API**：`GET /api/v1/quotation/tasks/{task_id}/u8-by-type-workbook` 鉴权流式下载 xlsx
- **前端**：报价页任务完成后提供下载 Excel

### v0.2.1（2026-04）

- 文档：同步前端路由（含 `/closing-form`、注册与用户/知识库管理页及权限说明）、Monorepo（pnpm + Turbo）与 `env.example` 说明

### v0.2.0（2026-03）

- 新增智能组合秤报单填写功能
- 新增聊天记录归档与用户画像摘要
- 新增 PDF 转图片与 OCR 信息提取
- 新增 WebSocket 实时任务进度推送
- 新增用户认证系统（JWT）
- 完成 Vue 3 前端应用（对话、报价/文件相关页、报单等）

### v0.1.0（2025-12）

- RAG 知识库检索系统上线
- 多格式文档处理管线
- 文件管理与对象存储集成

---

<div align="center">

Made with ❤️ by Shanghai Marinetime 331 Team

</div>
