<div align="center">

# 🚀 AI Data Tool

### 智能文档处理与 RAG 检索系统

<p align="center">
  <a href="#主要特性">特性</a> •
  <a href="#快速开始">快速开始</a> •
  <a href="#api-文档">API 文档</a> •
  <a href="#部署">部署</a> •
  <a href="#贡献">贡献</a>
</p>

![Python Version](https://img.shields.io/badge/python-3.12+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.116.1-009688.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![PyTorch](https://img.shields.io/badge/PyTorch-2.9.1-EE4C2C.svg)
![CUDA](https://img.shields.io/badge/CUDA-13.0-76B900.svg)

</div>

---

## 📖 简介

AI Data Tool 是一个功能强大的企业级 AI 数据处理平台，集成了 **RAG（检索增强生成）系统**、**智能文档解析**、**OCR 识别**、**数据分析** 等多种 AI 能力。基于 FastAPI 构建，支持高并发、分布式部署，适用于智能客服、知识库问答、文档智能处理等场景。

### 🎯 核心亮点

- ⚡ **高性能架构**：基于 FastAPI + Uvicorn，支持异步处理
- 🧠 **智能检索**：LlamaIndex + PgVector 向量数据库，毫秒级检索
- 📄 **全格式支持**：PDF、Word、Excel、PPT、HTML 等多格式文档解析
- 🔍 **OCR 识别**：PaddleOCR 高精度中英文识别
- 📊 **数据分析**：内置数据分析和可视化能力
- 🔐 **企业级安全**：JWT 认证、速率限制、权限控制
- 📈 **完善监控**：Prometheus 指标 + 健康检查

---

## 🌟 主要特性

<table>
<tr>
<td width="50%">

### 🤖 RAG 检索系统
- BGE-M3 嵌入模型
- Reranker 智能重排序
- PgVector 向量存储
- 混合检索（向量+关键词）
- 上下文感知问答

</td>
<td width="50%">

### 📝 文档处理
- PDF 智能解析
- Office 文档提取
- HTML 内容清洗
- 批量文档处理
- 自动分块与索引

</td>
</tr>
<tr>
<td width="50%">

### 🔤 OCR 识别
- 高精度文字识别
- 表格结构识别
- 图表智能提取
- 多语言支持
- GPU 加速推理

</td>
<td width="50%">

### 📊 数据分析
- 关键词自动提取
- 数据可视化
- 统计分析
- Excel 报表生成
- 自定义分析流程

</td>
</tr>
</table>

---

## 🚀 快速开始

### 前置要求

```bash
# 必需
- Python 3.12+
- PostgreSQL 14+ (with pgvector extension)
- Redis 6.0+

# 可选（用于对象存储）
- MinIO (latest)

# GPU 支持（可选）
- CUDA 13.0+
- NVIDIA GPU
```

### 一键安装

#### 1️⃣ 克隆仓库

```bash
git clone <your-repo-url>
cd project1
```

#### 2️⃣ 创建环境

```bash
# 使用 Conda
conda create -n ai_data_tool python=3.12
conda activate ai_data_tool

# 或使用 venv
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate  # Windows
```

#### 3️⃣ 安装依赖

```bash
pip install -r requirements.txt
```

#### 4️⃣ 配置环境

创建 `.env` 文件：

```bash
# 复制示例配置
cat > .env << EOF
# 基础配置
PROJECT_NAME=AI Data Tool
HOST=0.0.0.0
PORT=8000
DEBUG=True

# 数据库
POSTGRES_SERVER=localhost
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_password
POSTGRES_DB=postgres
POSTGRES_PORT=5432

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=your_redis_password

# MinIO
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin

# AI 服务
BGE_M3_API_URL=http://localhost:8001/api/embed
RERANKER_API_URL=http://localhost:8002/api/rerank

# 安全
SECRET_KEY=$(openssl rand -hex 32)
EOF
```

#### 5️⃣ 初始化数据库

```sql
-- 连接到 PostgreSQL 并执行
CREATE EXTENSION IF NOT EXISTS vector;
```

#### 6️⃣ 启动服务

```bash
# 开发模式
python main.py

# 或使用 uvicorn
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

#### 7️⃣ 访问服务

🎉 服务启动成功！访问以下地址：

| 服务 | 地址 |
|------|------|
| 🏠 主页 | http://localhost:8000 |
| 📚 Swagger UI | http://localhost:8000/api/v1/docs |
| 📖 ReDoc | http://localhost:8000/api/v1/redoc |
| ❤️ 健康检查 | http://localhost:8000/api/v1/health |
| 📊 Prometheus | http://localhost:8000/api/v1/metrics |

---

## 🏗️ 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                        客户端请求                            │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI 应用层                            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ CORS中间件│  │ 监控中间件│  │ 限流中间件│  │ 缓存中间件│   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
└─────────────────────┬───────────────────────────────────────┘
                      │
        ┌─────────────┼─────────────┐
        │             │             │
        ▼             ▼             ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│  RAG 检索    │ │  文档处理    │ │  数据分析    │
│              │ │              │ │              │
│ • BGE-M3    │ │ • PDF解析   │ │ • 关键词提取 │
│ • Reranker  │ │ • OCR识别   │ │ • 可视化     │
│ • PgVector  │ │ • 批量处理  │ │ • 统计分析   │
└──────┬───────┘ └──────┬───────┘ └──────┬───────┘
       │                │                │
       └────────────────┼────────────────┘
                        │
        ┌───────────────┼───────────────┐
        │               │               │
        ▼               ▼               ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│  PostgreSQL  │ │    Redis     │ │    MinIO     │
│  + PgVector  │ │    缓存层    │ │  对象存储    │
└──────────────┘ └──────────────┘ └──────────────┘
```

---

## 📂 项目结构

```
project1/
├── 📁 app/                          # 应用核心代码
│   ├── 📁 api/                      # API 路由
│   │   ├── 📁 v1/                   # API v1 版本
│   │   │   ├── __init__.py
│   │   │   ├── endpoints/           # 各功能端点
│   │   │   └── ...
│   │   └── taskmanager.py           # 异步任务管理
│   ├── 📁 core/                     # 核心模块
│   │   ├── cache.py                 # Redis 缓存
│   │   ├── config.py                # 配置管理
│   │   ├── database.py              # 数据库连接
│   │   ├── dependencies.py          # 依赖注入
│   │   ├── security.py              # 安全认证
│   │   ├── storage.py               # MinIO 存储
│   │   └── 📁 middleware/           # 中间件
│   ├── 📁 integrations/             # 第三方集成
│   │   └── 📁 monitoring/           # 监控集成
│   ├── 📁 models/                   # ORM 模型
│   ├── 📁 schemas/                  # Pydantic schemas
│   └── 📁 ragsystem/                # RAG 系统
│       ├── RAGretriever.py          # 检索器核心
│       ├── chart_analyze.py         # 图表分析
│       └── data_analyze.py          # 数据分析
├── 📁 vllm_monitor/                 # VLLM 模型监控
├── 📁 docs/                         # 文档
├── 📁 logs/                         # 日志文件
├── 📄 main.py                       # 应用入口
├── 📄 requirements.txt              # Python 依赖
├── 📄 .env                          # 环境变量（需创建）
├── 📄 .gitignore                    # Git 忽略规则
└── 📄 README.md                     # 本文档
```

---

## 🔧 技术栈

### 核心框架

![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-316192?style=for-the-badge&logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-DC382D?style=for-the-badge&logo=redis&logoColor=white)

### AI/ML 框架

| 类别 | 技术栈 |
|------|--------|
| **RAG 系统** | LlamaIndex, LangChain, PgVector |
| **深度学习** | PyTorch 2.9.1, CUDA 13.0 |
| **NLP** | Transformers, Sentence-Transformers |
| **OCR** | PaddleOCR, PaddlePaddle |
| **嵌入模型** | BGE-M3, Reranker |
| **关键词提取** | KeyBERT, NLTK |

### 数据处理

| 功能 | 工具 |
|------|------|
| **数据分析** | Pandas, Polars, NumPy |
| **可视化** | Plotly, Matplotlib |
| **文档解析** | pdfplumber, python-docx, openpyxl |
| **HTML 处理** | BeautifulSoup4, lxml |
| **图像处理** | OpenCV, Pillow |

### 基础设施

- **Web 服务器**: Uvicorn + Uvloop
- **异步 HTTP**: AIOHTTP, HTTPX
- **ORM**: SQLAlchemy 2.0
- **验证**: Pydantic v2
- **序列化**: orjson, ujson
- **监控**: Prometheus, ColorLog

---

## 🎯 核心功能详解

### RAG 检索系统

智能的检索增强生成系统，支持大规模文档的语义检索和问答。

```python
# 示例：使用 RAG 系统进行文档问答
from app.ragsystem.RAGretriever import create_rag_retriever_system

# 初始化 RAG 系统
rag = create_rag_retriever_system(
    host="localhost",
    user="postgres",
    password="password",
    database="postgres",
    bge_m3_api_url="http://localhost:8001/api/embed",
    reranker_api_url="http://localhost:8002/api/rerank",
    default_top_k=20,
    default_top_n=3
)

# 执行检索
results = rag.search(query="什么是机器学习？", top_k=5)
```

**特性：**
- 🔍 混合检索（向量 + BM25）
- 🧠 智能重排序
- 📊 相关度评分
- 🚀 毫秒级响应

### 文档处理

支持多种文档格式的智能解析和内容提取。

**支持格式：**
- 📄 PDF
- 📝 Word (.docx)
- 📊 Excel (.xlsx)
- 📑 PowerPoint (.pptx)
- 🌐 HTML
- 📃 纯文本

**功能：**
- 自动内容提取
- 结构化解析
- 图表识别
- 批量处理
- OCR 识别

### OCR 识别

基于 PaddleOCR 的高精度文字识别。

**特点：**
- ✅ 中英文混合识别
- ✅ 表格结构识别
- ✅ 手写字体支持
- ✅ GPU 加速
- ✅ 批量处理

---

## 🛠️ API 文档

### 健康检查

```bash
GET /api/v1/health
```

**响应示例：**
```json
{
  "status": "healthy",
  "services": {
    "database": {"status": "healthy"},
    "redis": {"status": "healthy"},
    "minio": {"status": "healthy"},
    "rag_system": {"status": "healthy"}
  }
}
```

### 监控指标

```bash
GET /api/v1/metrics
```

返回 Prometheus 格式的监控指标。

### 完整 API 文档

启动服务后访问：
- **Swagger UI**: http://localhost:8000/api/v1/docs
- **ReDoc**: http://localhost:8000/api/v1/redoc

---

## 🐳 部署

### Docker 部署（推荐）

#### 创建 Dockerfile

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    g++ \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/api/v1/health || exit 1

# 启动命令
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

#### Docker Compose

```yaml
version: '3.8'

services:
  app:
    build: .
    ports:
      - "8000:8000"
    environment:
      - POSTGRES_SERVER=postgres
      - REDIS_HOST=redis
      - MINIO_ENDPOINT=minio:9000
    depends_on:
      - postgres
      - redis
      - minio
    restart: unless-stopped

  postgres:
    image: pgvector/pgvector:pg14
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: password
      POSTGRES_DB: postgres
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    command: redis-server --requirepass redispassword
    volumes:
      - redis_data:/data
    restart: unless-stopped

  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    volumes:
      - minio_data:/data
    ports:
      - "9000:9000"
      - "9001:9001"
    restart: unless-stopped

volumes:
  postgres_data:
  redis_data:
  minio_data:
```

#### 启动服务

```bash
# 构建并启动
docker-compose up -d

# 查看日志
docker-compose logs -f app

# 停止服务
docker-compose down
```

### 生产环境部署

#### 使用 Gunicorn + Uvicorn Workers

```bash
gunicorn main:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --timeout 120 \
  --access-logfile /var/log/app/access.log \
  --error-logfile /var/log/app/error.log \
  --log-level info
```

#### Systemd 服务配置

```ini
# /etc/systemd/system/ai-data-tool.service
[Unit]
Description=AI Data Tool API Service
After=network.target postgresql.service redis.service

[Service]
Type=notify
User=www-data
Group=www-data
WorkingDirectory=/opt/ai-data-tool
Environment="PATH=/opt/ai-data-tool/venv/bin"
ExecStart=/opt/ai-data-tool/venv/bin/gunicorn main:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000
Restart=always

[Install]
WantedBy=multi-user.target
```

启动服务：
```bash
sudo systemctl daemon-reload
sudo systemctl enable ai-data-tool
sudo systemctl start ai-data-tool
sudo systemctl status ai-data-tool
```

---

## 🔒 安全性

### 认证机制

- **JWT Token**: 基于 JSON Web Token 的认证
- **密码加密**: bcrypt 哈希加密
- **Token 过期**: 可配置的 Token 有效期

### 安全特性

✅ CORS 配置  
✅ 请求速率限制  
✅ 请求大小限制  
✅ SQL 注入防护  
✅ XSS 防护  
✅ HTTPS 支持（生产环境推荐）

### 环境变量安全

```bash
# 不要在代码中硬编码敏感信息
# 使用环境变量或密钥管理服务

# 生成安全的 SECRET_KEY
openssl rand -hex 32
```

---

## 📊 监控与日志

### Prometheus 监控

系统内置 Prometheus 指标收集：

- **HTTP 指标**
  - 请求总数
  - 响应时间分布
  - 错误率统计
  
- **系统指标**
  - CPU 使用率
  - 内存使用
  - 数据库连接池

### 日志管理

```python
# 日志配置在 app/core/logging.py
# 支持多种日志级别和格式

import logging
logger = logging.getLogger(__name__)

logger.debug("调试信息")
logger.info("普通信息")
logger.warning("警告信息")
logger.error("错误信息")
logger.critical("严重错误")
```

**日志特性：**
- 🎨 彩色控制台输出
- 📁 自动按日期轮转
- 🔍 结构化日志格式
- 📊 日志聚合支持

---

## 🧪 测试

```bash
# 安装测试依赖
pip install pytest pytest-asyncio pytest-cov httpx

# 运行测试
pytest

# 生成覆盖率报告
pytest --cov=app --cov-report=html

# 查看覆盖率报告
open htmlcov/index.html
```

---

## 📈 性能优化

### 缓存策略

- **Redis 缓存**: API 响应缓存
- **查询缓存**: 数据库查询结果缓存
- **向量缓存**: 嵌入向量缓存

### 数据库优化

- **连接池**: SQLAlchemy 连接池管理
- **索引优化**: 关键字段索引
- **查询优化**: 分页查询、延迟加载

### 并发处理

- **异步 I/O**: FastAPI 原生异步支持
- **线程池**: 文档处理任务线程池
- **消息队列**: 长任务异步处理

---

## 🤝 贡献

欢迎贡献代码、报告问题或提出建议！

### 贡献流程

1. 🍴 Fork 本仓库
2. 🌿 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 💬 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 📤 推送到分支 (`git push origin feature/AmazingFeature`)
5. 🔃 提交 Pull Request

### 代码规范

- 遵循 PEP 8 Python 代码规范
- 添加必要的类型注解
- 编写单元测试
- 更新相关文档

---

## 📝 更新日志

### v0.0.1 (2025-12-11)

**新增功能**
- ✨ 完整的 RAG 检索系统
- ✨ 多格式文档处理
- ✨ OCR 识别功能
- ✨ 数据分析能力

**改进**
- ⚡ 优化检索性能
- 🔧 完善错误处理
- 📝 补充 API 文档

---

## ❓ 常见问题

<details>
<summary><b>Q: 如何启用 GPU 加速？</b></summary>

确保安装了 CUDA 13.0+ 和对应的 GPU 驱动。系统会自动检测并使用 GPU。

```python
import torch
print(torch.cuda.is_available())  # 检查 CUDA 是否可用
```
</details>

<details>
<summary><b>Q: 支持哪些文档格式？</b></summary>

目前支持：PDF、Word (.docx)、Excel (.xlsx)、PowerPoint (.pptx)、HTML、纯文本等格式。
</details>

<details>
<summary><b>Q: 如何自定义 BGE-M3 嵌入模型？</b></summary>

在 `.env` 文件中配置 `BGE_M3_API_URL` 指向你的模型服务地址。
</details>

<details>
<summary><b>Q: 数据库连接失败怎么办？</b></summary>

1. 检查 PostgreSQL 服务是否启动
2. 验证 `.env` 中的数据库配置
3. 确保安装了 pgvector 扩展
4. 检查防火墙和网络连接
</details>

---

## 📄 许可证

本项目采用 [MIT License](LICENSE) 开源协议。

```
MIT License

Copyright (c) 2024 AI Data Tool

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction...
```

---

## 🙏 致谢

感谢以下优秀的开源项目：

| 项目 | 描述 |
|------|------|
| [FastAPI](https://fastapi.tiangolo.com/) | 现代化的 Python Web 框架 |
| [LlamaIndex](https://www.llamaindex.ai/) | RAG 框架 |
| [LangChain](https://www.langchain.com/) | LLM 应用开发框架 |
| [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) | OCR 识别引擎 |
| [pgvector](https://github.com/pgvector/pgvector) | PostgreSQL 向量扩展 |

---

## 📞 联系我们

- 💬 提交 [Issue](../../issues)
- 📧 邮件联系
- 💼 商务合作

---

<div align="center">

**如果这个项目对你有帮助，请给个 ⭐️ Star 吧！**

Made with ❤️ by Shmtu 331

</div>

