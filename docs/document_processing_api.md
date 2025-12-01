# 文档处理 API 使用指南

## 📚 功能概述

异步文档处理系统，支持：
- 多文件批量上传
- 后台异步处理（不阻塞 API）
- 实时进度追踪
- 任务状态查询
- 优雅的线程池管理

## 🚀 API 端点

### 1. 提交文档处理任务

```http
POST /api/v1/docs/process
Content-Type: multipart/form-data

参数：
- files: 文件列表（支持多文件）
- instance_id: 知识库实例ID（必填）
- chunk_size: 文本块大小（可选，默认500）
- chunk_overlap: 文本块重叠大小（可选，默认50）
- uploader: 上传者标识（可选，默认anonymous）
```

**响应示例**：
```json
{
  "task_id": "doc_process_20251201_143022_a1b2c3d4",
  "status": "pending",
  "message": "任务已创建，开始处理",
  "files_count": 3
}
```

### 2. 查询任务状态

```http
GET /api/v1/docs/status/{task_id}
```

**响应示例**：
```json
{
  "task_id": "doc_process_20251201_143022_a1b2c3d4",
  "status": "running",
  "progress": 45,
  "message": "正在处理第2/3个文件...",
  "created_at": "2025-12-01T14:30:22",
  "started_at": "2025-12-01T14:30:23",
  "completed_at": null,
  "result": null,
  "error": null
}
```

**状态说明**：
- `pending`: 等待处理
- `running`: 正在处理
- `completed`: 处理完成
- `failed`: 处理失败

### 3. 获取任务列表

```http
GET /api/v1/docs/tasks?status=running&limit=10
```

**参数**：
- `status`: 可选，按状态筛选（pending/running/completed/failed）
- `limit`: 返回数量限制（1-100，默认10）

**响应示例**：
```json
{
  "tasks": [
    {
      "task_id": "doc_process_xxx",
      "status": "running",
      "progress": 75,
      ...
    }
  ],
  "total": 5
}
```

### 4. 删除任务

```http
DELETE /api/v1/docs/tasks/{task_id}
```

**响应示例**：
```json
{
  "success": true,
  "message": "任务 doc_process_xxx 已删除"
}
```

## 💻 使用示例

### Python 客户端

```python
import requests
import time

# 1. 提交文档处理任务
url = "http://localhost:8000/api/v1/docs/process"
files = [
    ('files', open('document1.pdf', 'rb')),
    ('files', open('document2.docx', 'rb')),
]
data = {
    'instance_id': 1,
    'chunk_size': 500,
    'uploader': 'user123'
}

response = requests.post(url, files=files, data=data)
result = response.json()
task_id = result['task_id']

print(f"任务已提交: {task_id}")

# 2. 轮询查询进度
while True:
    status_url = f"http://localhost:8000/api/v1/docs/status/{task_id}"
    status = requests.get(status_url).json()
    
    print(f"状态: {status['status']}, 进度: {status['progress']}%, 消息: {status['message']}")
    
    if status['status'] in ['completed', 'failed']:
        break
    
    time.sleep(2)  # 每2秒查询一次

# 3. 获取结果
if status['status'] == 'completed':
    print("处理成功!")
    print(f"结果: {status['result']}")
else:
    print(f"处理失败: {status['error']}")
```

### JavaScript/前端

```javascript
// 1. 提交任务
async function submitDocumentProcessing(files, instanceId) {
  const formData = new FormData();
  
  files.forEach(file => formData.append('files', file));
  formData.append('instance_id', instanceId);
  formData.append('chunk_size', 500);
  
  const response = await fetch('/api/v1/docs/process', {
    method: 'POST',
    body: formData
  });
  
  return await response.json();
}

// 2. 轮询进度
async function pollTaskStatus(taskId, onProgress, onComplete) {
  const intervalId = setInterval(async () => {
    const response = await fetch(`/api/v1/docs/status/${taskId}`);
    const status = await response.json();
    
    // 更新进度
    onProgress(status);
    
    // 完成或失败时停止轮询
    if (status.status === 'completed' || status.status === 'failed') {
      clearInterval(intervalId);
      onComplete(status);
    }
  }, 2000);
}

// 使用示例
const files = document.getElementById('fileInput').files;
const result = await submitDocumentProcessing(files, 1);

pollTaskStatus(
  result.task_id,
  (status) => {
    // 更新进度条
    document.getElementById('progress').style.width = `${status.progress}%`;
    document.getElementById('message').textContent = status.message;
  },
  (finalStatus) => {
    if (finalStatus.status === 'completed') {
      alert('处理完成!');
      console.log(finalStatus.result);
    } else {
      alert('处理失败: ' + finalStatus.error);
    }
  }
);
```

### cURL 命令

```bash
# 1. 提交任务
curl -X POST "http://localhost:8000/api/v1/docs/process?instance_id=1&uploader=test" \
  -F "files=@document1.pdf" \
  -F "files=@document2.docx"

# 2. 查询状态
curl "http://localhost:8000/api/v1/docs/status/doc_process_20251201_143022_a1b2c3d4"

# 3. 获取任务列表
curl "http://localhost:8000/api/v1/docs/tasks?status=running&limit=5"

# 4. 删除任务
curl -X DELETE "http://localhost:8000/api/v1/docs/tasks/doc_process_20251201_143022_a1b2c3d4"
```

## ⚙️ 配置说明

在 `.env` 文件中添加配置：

```bash
# 文档处理线程池大小（可选，默认4）
DOC_PROCESSING_WORKERS=4

# 数据库配置（必需）
POSTGRES_SERVER=localhost
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_password
POSTGRES_DB=your_database
POSTGRES_PORT=5432
```

## 🔧 线程池管理

### 生命周期

线程池在应用启动时自动创建，应用关闭时优雅关闭：

```python
# 应用关闭时（自动调用）
- 等待所有正在运行的任务完成（最多30秒）
- 关闭线程池
- 释放资源
```

### 手动控制

如果需要手动控制线程池：

```python
from app.api.v1.document_processing import executor_manager

# 获取线程池状态
executor = executor_manager.executor

# 优雅关闭（等待任务完成）
executor_manager.shutdown(wait=True, timeout=30)

# 强制关闭（取消未完成任务）
executor_manager.shutdown(wait=False)
```

## 📊 性能说明

- **并发处理**: 默认4个工作线程，可通过 `DOC_PROCESSING_WORKERS` 配置
- **内存优化**: 使用流式上传/下载，避免大文件占用内存
- **进度追踪**: 实时更新处理进度（下载30%、处理70%）
- **错误隔离**: 单个文件失败不影响其他文件

## 🐛 常见问题

### Q: 如何处理大量文件？
A: 分批提交任务，每批 10-20 个文件，避免单个任务过大。

### Q: 任务可以取消吗？
A: 已提交到线程池的任务无法中途取消，但可以删除任务记录。

### Q: 如何重试失败的任务？
A: 查询失败任务的 `metadata.file_ids`，重新提交处理请求。

### Q: 线程池满了会怎样？
A: 新任务会进入队列等待，不会丢失。建议增加 `DOC_PROCESSING_WORKERS`。

## 🚀 升级到 Celery

如果需要分布式处理，可以平滑升级到 Celery：

```python
# 1. 安装依赖
pip install celery redis

# 2. 修改提交任务代码
from app.tasks import process_documents_task

# 改为 Celery 异步调用
process_documents_task.delay(task_id, file_ids, instance_id)
```

核心处理逻辑无需修改，只需改变任务调度方式。
