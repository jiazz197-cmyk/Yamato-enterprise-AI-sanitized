# 文档处理服务使用指南

## 概述

文档处理服务提供了完整的文档解析、分块、向量化和存储功能，支持多种文档格式的异步处理。

## 支持的文件格式

- **Office 文档**: `.doc`, `.docx`, `.xls`, `.xlsx`, `.ppt`, `.pptx`
- **PDF 文档**: `.pdf` (支持 OCR 文字识别)
- **文本文档**: `.txt`, `.md`, `.json`
- **网页文档**: `.html`, `.htm`

## API 端点

### 1. 提交文档处理任务

**接口**: `POST /api/v1/docs/process`

**功能**: 上传文件并创建异步处理任务，将文档分块后存储到向量数据库。

**请求参数**:

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `files` | File[] | 是 | - | 要处理的文档文件（支持多文件上传） |
| `instance_id` | int | 是 | - | 知识库实例 ID |
| `chunk_size` | int | 否 | 500 | 文本块大小（100-2000 tokens） |
| `chunk_overlap` | int | 否 | 50 | 文本块重叠大小（0-500 tokens） |
| `uploader` | string | 否 | anonymous | 上传者标识 |

**响应示例**:

```json
{
  "task_id": "doc_process_20231204_151121_964_fc33b692",
  "status": "pending",
  "message": "任务已创建，开始处理",
  "files_count": 3
}
```

**使用示例 (curl)**:

```bash
curl -X POST "http://localhost:8000/api/v1/docs/process?instance_id=1&chunk_size=500&chunk_overlap=50" \
  -H "Content-Type: multipart/form-data" \
  -F "files=@document1.pdf" \
  -F "files=@document2.docx" \
  -F "files=@document3.txt"
```

**使用示例 (Python)**:

```python
import requests

url = "http://localhost:8000/api/v1/docs/process"
files = [
    ("files", ("document1.pdf", open("document1.pdf", "rb"), "application/pdf")),
    ("files", ("document2.docx", open("document2.docx", "rb"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))
]
params = {
    "instance_id": 1,
    "chunk_size": 500,
    "chunk_overlap": 50,
    "uploader": "user123"
}

response = requests.post(url, files=files, params=params)
result = response.json()
print(f"任务 ID: {result['task_id']}")
```

---

### 2. 查询任务状态

**接口**: `GET /api/v1/docs/status/{task_id}`

**功能**: 获取指定任务的处理进度和状态。

**路径参数**:
- `task_id`: 任务 ID（提交任务时返回）

**响应示例**:

```json
{
  "task_id": "doc_process_20231204_151121_964_fc33b692",
  "status": "running",
  "progress": 65,
  "message": "正在处理第 2/3 个文件: document2.docx",
  "created_at": "2023-12-04T15:11:21.964000",
  "started_at": "2023-12-04T15:11:22.123000",
  "completed_at": null,
  "result": null,
  "error": null
}
```

**任务状态说明**:

| 状态 | 说明 |
|------|------|
| `pending` | 任务已创建，等待执行 |
| `running` | 任务正在执行中 |
| `completed` | 任务已完成 |
| `failed` | 任务执行失败 |
| `cancelled` | 任务已取消 |

**使用示例**:

```bash
curl -X GET "http://localhost:8000/api/v1/docs/status/doc_process_20231204_151121_964_fc33b692"
```

```python
import requests

task_id = "doc_process_20231204_151121_964_fc33b692"
response = requests.get(f"http://localhost:8000/api/v1/docs/status/{task_id}")
status = response.json()
print(f"进度: {status['progress']}% - {status['message']}")
```

---

### 3. 取消任务

**接口**: `POST /api/v1/docs/cancel/{task_id}`

**功能**: 取消正在执行或等待中的任务。

**路径参数**:
- `task_id`: 任务 ID

**响应示例**:

```json
{
  "task_id": "doc_process_20231204_151121_964_fc33b692",
  "status": "cancelled",
  "message": "任务已取消"
}
```

**使用示例**:

```bash
curl -X POST "http://localhost:8000/api/v1/docs/cancel/doc_process_20231204_151121_964_fc33b692"
```

---

### 4. 获取任务列表

**接口**: `GET /api/v1/docs/tasks`

**功能**: 获取所有任务的列表（支持分页和状态过滤）。

**查询参数**:

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `status` | string | 否 | - | 过滤状态 (pending/running/completed/failed) |
| `skip` | int | 否 | 0 | 跳过记录数 |
| `limit` | int | 否 | 100 | 返回记录数上限 |

**响应示例**:

```json
{
  "tasks": [
    {
      "task_id": "doc_process_20231204_151121_964_fc33b692",
      "status": "completed",
      "progress": 100,
      "message": "处理完成: 成功处理 3 个文件",
      "created_at": "2023-12-04T15:11:21.964000",
      "started_at": "2023-12-04T15:11:22.123000",
      "completed_at": "2023-12-04T15:12:05.456000",
      "result": {
        "total_chunks": 245,
        "total_files": 3
      },
      "error": null
    }
  ],
  "total": 1
}
```

**使用示例**:

```bash
# 获取所有运行中的任务
curl -X GET "http://localhost:8000/api/v1/docs/tasks?status=running&limit=10"
```

---

## 处理流程

文档处理分为以下阶段：

1. **文件上传** (0-10%): 上传文件到 MinIO 对象存储
2. **文件下载** (10-30%): 从 MinIO 下载文件到处理器
3. **文档解析** (30-60%): 解析文档内容（PDF OCR、Office 转换等）
4. **文本分块** (60-80%): 根据 `chunk_size` 和 `chunk_overlap` 切分文本
5. **向量化存储** (80-100%): 生成向量嵌入并存储到 PostgreSQL + pgvector

## 配置参数说明

### chunk_size (文本块大小)

- **含义**: 每个文本块包含的最大 token 数量
- **推荐值**: 
  - 问答场景: 300-500
  - 检索场景: 500-800
  - 长文档分析: 800-1500
- **注意**: 值越大，单个块包含的上下文越多，但检索精度可能降低

### chunk_overlap (文本块重叠)

- **含义**: 相邻文本块之间的重叠 token 数量
- **推荐值**: `chunk_size` 的 10%-20%
- **作用**: 防止关键信息在分块边界被截断

### instance_id (知识库实例 ID)

- **含义**: 指定文档存储的目标知识库
- **获取方式**: 需要先通过知识库管理 API 创建实例

## 错误处理

### 常见错误码

| 状态码 | 错误类型 | 说明 |
|--------|----------|------|
| 400 | ValidationError | 参数验证失败（文件格式不支持、参数范围错误） |
| 404 | NotFoundError | 任务不存在或知识库实例不存在 |
| 413 | PayloadTooLarge | 文件大小超过限制 (50MB) |
| 422 | UnprocessableEntity | 文档解析失败 |
| 500 | InternalServerError | 服务器内部错误 |

### 错误响应示例

```json
{
  "detail": "不支持的文件类型: 'avi' (支持的格式: doc, docx, pdf, txt, md, html, json, xls, xlsx, ppt, pptx)"
}
```

## 高级用法

### 轮询任务状态直到完成

```python
import requests
import time

def wait_for_task_completion(task_id, timeout=300, interval=2):
    """轮询任务状态直到完成或超时"""
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        response = requests.get(f"http://localhost:8000/api/v1/docs/status/{task_id}")
        status = response.json()
        
        if status["status"] in ["completed", "failed", "cancelled"]:
            return status
        
        print(f"进度: {status['progress']}% - {status['message']}")
        time.sleep(interval)
    
    raise TimeoutError(f"任务 {task_id} 超时")

# 使用示例
task_id = "doc_process_20231204_151121_964_fc33b692"
final_status = wait_for_task_completion(task_id)
print(f"任务完成: {final_status['result']}")
```

### 批量处理文件夹

```python
import os
import requests
from pathlib import Path

def process_folder(folder_path, instance_id, chunk_size=500):
    """批量处理文件夹中的所有文档"""
    folder = Path(folder_path)
    supported_exts = {'.pdf', '.docx', '.doc', '.txt', '.md', '.html', '.xlsx', '.pptx'}
    
    files_to_upload = []
    for file_path in folder.rglob('*'):
        if file_path.suffix.lower() in supported_exts:
            files_to_upload.append(
                ("files", (file_path.name, open(file_path, "rb")))
            )
    
    if not files_to_upload:
        print("未找到支持的文件")
        return
    
    print(f"发现 {len(files_to_upload)} 个文件，开始上传...")
    
    response = requests.post(
        "http://localhost:8000/api/v1/docs/process",
        files=files_to_upload,
        params={"instance_id": instance_id, "chunk_size": chunk_size}
    )
    
    result = response.json()
    print(f"任务已创建: {result['task_id']}")
    return result['task_id']

# 使用示例
task_id = process_folder("./documents", instance_id=1, chunk_size=500)
```

## 性能优化建议

1. **批量上传**: 一次提交多个文件比多次单文件提交效率更高
2. **合理设置 chunk_size**: 
   - 小文件 (< 10 页): chunk_size=300-500
   - 大文件 (> 100 页): chunk_size=800-1200
3. **避免频繁轮询**: 查询任务状态的间隔建议 ≥ 2 秒
4. **异步处理**: 提交任务后立即返回，通过任务 ID 异步查询结果

## 依赖服务

文档处理服务依赖以下组件：

- **MinIO**: 对象存储，保存上传的原始文件
- **PostgreSQL + pgvector**: 向量数据库，存储文本块和嵌入向量
- **Redis** (可选): 任务状态缓存，提升查询性能
- **LibreOffice** (Windows): `.doc` 文件转换（需要安装在 `C:\Program Files\LibreOffice\`）
- **PaddleOCR** (可选): PDF OCR 文字识别

## 故障排查

### 问题：任务一直处于 pending 状态

**原因**: 线程池可能已满或服务未启动

**解决方法**:
1. 检查日志中是否有 "ThreadPoolExecutor initialized" 
2. 确认 `settings.py` 中 `MAX_WORKERS` 配置
3. 重启服务

### 问题：.doc 文件处理失败

**原因**: LibreOffice 未安装或路径错误

**解决方法**:
1. Windows: 安装 LibreOffice 到默认路径 `C:\Program Files\LibreOffice\`
2. 检查日志中的 "未检测到LibreOffice" 错误
3. 或者将 `.doc` 文件转换为 `.docx` 后上传

### 问题：PDF 解析结果为空

**原因**: PDF 是扫描版（纯图片），需要 OCR

**解决方法**:
1. 安装 PaddleOCR: `pip install paddleocr paddlepaddle`
2. 或使用其他工具预先提取 PDF 文本

## API 文档

完整的交互式 API 文档可通过以下地址访问：

- Swagger UI: `http://localhost:8000/api/v1/docs`
- ReDoc: `http://localhost:8000/api/v1/redoc`

## 相关文档

- [知识库管理 API](./knowledge_base_guide.md)
- [向量检索 API](./vector_search_guide.md)
- [部署指南](./deployment_guide.md)
