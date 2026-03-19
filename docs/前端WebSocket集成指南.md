# 前端 WebSocket 集成指南

> 📱 **本文档面向前端开发者**，介绍如何集成文档处理任务的 WebSocket 实时推送功能。

---

## 📖 目录

1. [快速开始](#1-快速开始)
2. [API 接口说明](#2-api-接口说明)
3. [WebSocket 消息格式](#3-websocket-消息格式)
4. [JavaScript 完整示例](#4-javascript-完整示例)
5. [React 集成示例](#5-react-集成示例)
6. [Vue 集成示例](#6-vue-集成示例)
7. [测试工具使用](#7-测试工具使用)
8. [错误处理](#8-错误处理)
9. [最佳实践](#9-最佳实践)

---

## 1. 快速开始

### 1.1 基本流程

```javascript
// Step 1: 提交文档处理任务
const taskId = await submitDocumentTask(file);

// Step 2: 建立 WebSocket 连接接收实时进度
const ws = new WebSocket(`ws://localhost:8000/api/v1/docs/ws/${taskId}`);

// Step 3: 监听消息
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(`进度: ${data.progress}%`);
  
  if (data.status === 'completed') {
    console.log('任务完成！', data.result);
  }
};
```

### 1.2 5 分钟快速测试

1. **使用测试页面**：
   - 打开 `test_websocket.html` 文件（在浏览器中）
   - 先通过 API 提交任务获取 `task_id`
   - 在测试页面输入 `task_id`
   - 点击"连接 WebSocket"
   - 实时查看任务进度

2. **效果预览**：
   ```
   📡 WebSocket 任务进度实时监控
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   任务进度: ████████░░░░  75%
   状态: 运行中
   正在处理第 1/1 个文件...
   ```

---

## 2. API 接口说明

### 2.1 提交文档处理任务

**接口地址：** `POST /api/v1/docs/process`

**请求参数（form-data）：**

| 参数 | 类型 | 必填 | 说明 |
|-----|------|-----|------|
| files | File[] | ✅ | 要处理的文档文件（支持多文件） |
| instance_id | int | ✅ | 知识库实例ID |
| chunk_size | int | ❌ | 文本块大小（默认500） |
| chunk_overlap | int | ❌ | 文本块重叠大小（默认50） |
| uploader | string | ❌ | 上传者标识（默认"anonymous"） |

**响应示例：**

```json
{
  "task_id": "doc_process_20260113_120530_abc12345",
  "status": "pending",
  "message": "任务已创建，开始处理",
  "files_count": 1
}
```

**JavaScript 示例：**

```javascript
async function submitDocumentTask(file, instanceId = 1) {
  const formData = new FormData();
  formData.append('files', file);
  formData.append('instance_id', instanceId);
  formData.append('chunk_size', 500);
  formData.append('chunk_overlap', 50);
  
  const response = await fetch('http://localhost:8000/api/v1/docs/process', {
    method: 'POST',
    body: formData
  });
  
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }
  
  const result = await response.json();
  return result.task_id;
}
```

### 2.2 建立 WebSocket 连接

**连接地址：** `ws://localhost:8000/api/v1/docs/ws/{task_id}`

**参数说明：**

| 参数 | 类型 | 说明 |
|-----|------|------|
| task_id | string | 任务ID（从提交任务接口获取） |

**连接示例：**

```javascript
const taskId = 'doc_process_20260113_120530_abc12345';
const ws = new WebSocket(`ws://localhost:8000/api/v1/docs/ws/${taskId}`);

ws.onopen = () => {
  console.log('✅ WebSocket 连接成功');
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('收到消息:', data);
};

ws.onerror = (error) => {
  console.error('❌ WebSocket 错误:', error);
};

ws.onclose = () => {
  console.log('🔌 WebSocket 连接已关闭');
};
```

### 2.3 查询任务状态（轮询备用方案）

**接口地址：** `GET /api/v1/docs/status/{task_id}`

**响应示例：**

```json
{
  "task_id": "doc_process_20260113_120530_abc12345",
  "status": "running",
  "progress": 50,
  "message": "正在处理...",
  "created_at": "2026-01-13T12:05:30.123456",
  "started_at": "2026-01-13T12:05:31.234567",
  "completed_at": null,
  "result": null,
  "error": null
}
```

**使用场景：** WebSocket 不可用时的降级方案（不推荐，仅作备用）

---

## 3. WebSocket 消息格式

### 3.1 连接成功消息

当 WebSocket 连接建立后，服务端会发送一条欢迎消息：

```json
{
  "type": "connection_established",
  "task_id": "doc_process_20260113_120530_abc12345",
  "message": "已订阅任务 doc_process_20260113_120530_abc12345 的实时更新"
}
```

### 3.2 任务事件消息

所有任务状态变化都会推送以下格式的消息：

```json
{
  "type": "task_event",
  "event_type": "task_progress_updated",
  "task_id": "doc_process_20260113_120530_abc12345",
  "task_type": "doc_process",
  "status": "running",
  "progress": 50,
  "message": "正在处理第 1/1 个文件...",
  "result": null,
  "error": null,
  "timestamp": "2026-01-13T12:05:35.123456"
}
```

**字段说明：**

| 字段 | 类型 | 说明 |
|-----|------|------|
| type | string | 消息类型（固定为 "task_event"） |
| event_type | string | 事件类型（见下表） |
| task_id | string | 任务ID |
| task_type | string | 任务类型（doc_process） |
| status | string | 任务状态：pending/running/completed/failed |
| progress | int | 进度百分比（0-100） |
| message | string | 描述信息 |
| result | object | 结果数据（仅在 completed 时有值） |
| error | string | 错误信息（仅在 failed 时有值） |
| timestamp | string | 事件时间戳（ISO 8601 格式） |

### 3.3 事件类型

| event_type | 说明 | 触发时机 |
|-----------|------|---------|
| `task_created` | 任务创建 | 任务创建成功时 |
| `task_started` | 任务启动 | 任务开始执行时 |
| `task_progress_updated` | 进度更新 | 任务进度变化时（可能多次） |
| `task_completed` | 任务完成 | 任务成功完成时 |
| `task_failed` | 任务失败 | 任务执行失败时 |

### 3.4 完整消息流示例

```javascript
// 消息 1: 连接确认
{
  "type": "connection_established",
  "task_id": "doc_process_20260113_120530_abc12345",
  "message": "已订阅任务 doc_process_20260113_120530_abc12345 的实时更新"
}

// 消息 2: 任务创建
{
  "type": "task_event",
  "event_type": "task_created",
  "status": "pending",
  "progress": 0,
  "message": ""
}

// 消息 3: 任务启动
{
  "type": "task_event",
  "event_type": "task_started",
  "status": "running",
  "progress": 0,
  "message": ""
}

// 消息 4-N: 进度更新（可能多次）
{
  "type": "task_event",
  "event_type": "task_progress_updated",
  "status": "running",
  "progress": 25,
  "message": "正在下载第 1/1 个文件: example.pdf"
}

{
  "type": "task_event",
  "event_type": "task_progress_updated",
  "status": "running",
  "progress": 50,
  "message": "开始处理 1 个文件..."
}

{
  "type": "task_event",
  "event_type": "task_progress_updated",
  "status": "running",
  "progress": 90,
  "message": "正在保存结果..."
}

// 最后消息: 任务完成
{
  "type": "task_event",
  "event_type": "task_completed",
  "status": "completed",
  "progress": 100,
  "message": "文档处理完成",
  "result": {
    "processed_files": 1,
    "total_files": 1,
    "status": "success",
    "instance_id": 1
  },
  "error": null
}
```

---

## 4. JavaScript 完整示例

### 4.1 封装 WebSocket 客户端

```javascript
/**
 * Document Task WebSocket Client
 * 文档任务 WebSocket 客户端封装
 */
class DocumentTaskClient {
  constructor(baseUrl = 'http://localhost:8000') {
    this.baseUrl = baseUrl;
    this.ws = null;
    this.taskId = null;
  }
  
  /**
   * 提交文档处理任务
   * @param {File} file - 文件对象
   * @param {number} instanceId - 知识库实例ID
   * @returns {Promise<string>} - 任务ID
   */
  async submitTask(file, instanceId = 1) {
    const formData = new FormData();
    formData.append('files', file);
    formData.append('instance_id', instanceId);
    formData.append('chunk_size', 500);
    formData.append('chunk_overlap', 50);
    
    try {
      const response = await fetch(`${this.baseUrl}/api/v1/docs/process`, {
        method: 'POST',
        body: formData
      });
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      
      const result = await response.json();
      this.taskId = result.task_id;
      return this.taskId;
      
    } catch (error) {
      console.error('提交任务失败:', error);
      throw error;
    }
  }
  
  /**
   * 连接 WebSocket 监听任务进度
   * @param {string} taskId - 任务ID
   * @param {Object} callbacks - 回调函数
   */
  connect(taskId, callbacks = {}) {
    const {
      onOpen = () => {},
      onProgress = () => {},
      onCompleted = () => {},
      onFailed = () => {},
      onError = () => {},
      onClose = () => {}
    } = callbacks;
    
    this.taskId = taskId;
    const wsUrl = this.baseUrl.replace('http', 'ws') + `/api/v1/docs/ws/${taskId}`;
    
    this.ws = new WebSocket(wsUrl);
    
    this.ws.onopen = () => {
      console.log('✅ WebSocket 连接成功');
      onOpen();
    };
    
    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        
        // 连接确认消息
        if (data.type === 'connection_established') {
          console.log(data.message);
          return;
        }
        
        // 任务事件消息
        if (data.type === 'task_event') {
          this.handleTaskEvent(data, {
            onProgress,
            onCompleted,
            onFailed
          });
        }
        
      } catch (error) {
        console.error('解析消息失败:', error);
      }
    };
    
    this.ws.onerror = (error) => {
      console.error('❌ WebSocket 错误:', error);
      onError(error);
    };
    
    this.ws.onclose = () => {
      console.log('🔌 WebSocket 连接已关闭');
      onClose();
    };
  }
  
  /**
   * 处理任务事件
   * @private
   */
  handleTaskEvent(data, callbacks) {
    const { event_type, progress, message, status, result, error } = data;
    
    // 记录日志
    console.log(`[${event_type}] 进度: ${progress}% - ${message}`);
    
    // 根据事件类型调用回调
    switch (event_type) {
      case 'task_created':
      case 'task_started':
      case 'task_progress_updated':
        callbacks.onProgress({
          progress,
          message,
          status,
          eventType: event_type
        });
        break;
      
      case 'task_completed':
        callbacks.onCompleted({
          result,
          message
        });
        this.disconnect();
        break;
      
      case 'task_failed':
        callbacks.onFailed({
          error,
          message
        });
        this.disconnect();
        break;
    }
  }
  
  /**
   * 断开 WebSocket 连接
   */
  disconnect() {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }
  
  /**
   * 查询任务状态（轮询备用方案）
   * @param {string} taskId - 任务ID
   * @returns {Promise<Object>} - 任务状态
   */
  async getTaskStatus(taskId) {
    try {
      const response = await fetch(`${this.baseUrl}/api/v1/docs/status/${taskId}`);
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      
      return await response.json();
      
    } catch (error) {
      console.error('查询任务状态失败:', error);
      throw error;
    }
  }
}

// 使用示例
const client = new DocumentTaskClient('http://localhost:8000');

// 方式 1: 先提交任务，再连接
async function example1() {
  const fileInput = document.getElementById('fileInput');
  const file = fileInput.files[0];
  
  // 提交任务
  const taskId = await client.submitTask(file, 1);
  console.log('任务已创建:', taskId);
  
  // 连接 WebSocket
  client.connect(taskId, {
    onOpen: () => {
      console.log('开始监听任务进度');
    },
    
    onProgress: ({ progress, message }) => {
      console.log(`进度: ${progress}%`, message);
      updateUI(progress, message);
    },
    
    onCompleted: ({ result, message }) => {
      console.log('任务完成！', result);
      showSuccessNotification(message, result);
    },
    
    onFailed: ({ error, message }) => {
      console.error('任务失败！', error);
      showErrorNotification(message, error);
    },
    
    onError: (error) => {
      console.error('连接错误', error);
    },
    
    onClose: () => {
      console.log('连接已关闭');
    }
  });
}

// 方式 2: 只连接已有任务
function example2() {
  const existingTaskId = 'doc_process_20260113_120530_abc12345';
  
  client.connect(existingTaskId, {
    onProgress: ({ progress, message }) => {
      document.getElementById('progress').textContent = `${progress}%`;
      document.getElementById('status').textContent = message;
    },
    
    onCompleted: ({ result }) => {
      alert('任务完成！');
      console.log(result);
    }
  });
}
```

### 4.2 UI 更新辅助函数

```javascript
/**
 * 更新进度条
 */
function updateProgressBar(percent) {
  const progressBar = document.getElementById('progressBar');
  const progressText = document.getElementById('progressText');
  
  progressBar.style.width = `${percent}%`;
  progressText.textContent = `${percent}%`;
  
  // 添加动画效果
  progressBar.style.transition = 'width 0.3s ease';
}

/**
 * 更新状态文本
 */
function updateStatusText(text, type = 'info') {
  const statusElement = document.getElementById('statusText');
  statusElement.textContent = text;
  
  // 根据类型设置颜色
  const colors = {
    info: '#2196F3',
    success: '#4CAF50',
    error: '#F44336',
    warning: '#FF9800'
  };
  
  statusElement.style.color = colors[type] || colors.info;
}

/**
 * 显示成功通知
 */
function showSuccessNotification(message, result) {
  const notification = document.createElement('div');
  notification.className = 'notification success';
  notification.innerHTML = `
    <h4>✅ 任务完成</h4>
    <p>${message}</p>
    <pre>${JSON.stringify(result, null, 2)}</pre>
  `;
  
  document.body.appendChild(notification);
  
  setTimeout(() => {
    notification.remove();
  }, 5000);
}

/**
 * 显示错误通知
 */
function showErrorNotification(message, error) {
  const notification = document.createElement('div');
  notification.className = 'notification error';
  notification.innerHTML = `
    <h4>❌ 任务失败</h4>
    <p>${message}</p>
    <p class="error-detail">${error}</p>
  `;
  
  document.body.appendChild(notification);
  
  setTimeout(() => {
    notification.remove();
  }, 5000);
}

/**
 * 显示结果详情
 */
function displayResult(result) {
  const resultContainer = document.getElementById('resultContainer');
  resultContainer.innerHTML = `
    <div class="result-card">
      <h3>📦 处理结果</h3>
      <div class="result-item">
        <span class="label">处理文件数:</span>
        <span class="value">${result.processed_files}</span>
      </div>
      <div class="result-item">
        <span class="label">总文件数:</span>
        <span class="value">${result.total_files}</span>
      </div>
      <div class="result-item">
        <span class="label">状态:</span>
        <span class="value success">${result.status}</span>
      </div>
      <div class="result-item">
        <span class="label">实例ID:</span>
        <span class="value">${result.instance_id}</span>
      </div>
    </div>
  `;
  resultContainer.style.display = 'block';
}
```

---

## 5. React 集成示例

### 5.1 自定义 Hook

```jsx
import { useState, useEffect, useRef } from 'react';

/**
 * useDocumentTask - React Hook for document processing with WebSocket
 */
export function useDocumentTask(baseUrl = 'http://localhost:8000') {
  const [taskId, setTaskId] = useState(null);
  const [status, setStatus] = useState('idle'); // idle, connecting, connected, processing, completed, failed
  const [progress, setProgress] = useState(0);
  const [message, setMessage] = useState('');
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  
  const wsRef = useRef(null);
  
  /**
   * 提交任务
   */
  const submitTask = async (file, instanceId = 1) => {
    const formData = new FormData();
    formData.append('files', file);
    formData.append('instance_id', instanceId);
    formData.append('chunk_size', 500);
    formData.append('chunk_overlap', 50);
    
    try {
      const response = await fetch(`${baseUrl}/api/v1/docs/process`, {
        method: 'POST',
        body: formData
      });
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      
      const data = await response.json();
      setTaskId(data.task_id);
      connectWebSocket(data.task_id);
      return data.task_id;
      
    } catch (err) {
      setError(err.message);
      setStatus('failed');
      throw err;
    }
  };
  
  /**
   * 连接 WebSocket
   */
  const connectWebSocket = (id) => {
    const wsUrl = baseUrl.replace('http', 'ws') + `/api/v1/docs/ws/${id}`;
    
    setStatus('connecting');
    wsRef.current = new WebSocket(wsUrl);
    
    wsRef.current.onopen = () => {
      setStatus('connected');
    };
    
    wsRef.current.onmessage = (event) => {
      const data = JSON.parse(event.data);
      
      if (data.type === 'task_event') {
        const { event_type, progress: p, message: msg, status: s, result: r, error: e } = data;
        
        setProgress(p || 0);
        setMessage(msg || '');
        
        if (event_type === 'task_started' || event_type === 'task_progress_updated') {
          setStatus('processing');
        } else if (event_type === 'task_completed') {
          setStatus('completed');
          setResult(r);
        } else if (event_type === 'task_failed') {
          setStatus('failed');
          setError(e);
        }
      }
    };
    
    wsRef.current.onerror = (err) => {
      setError('WebSocket connection error');
      setStatus('failed');
    };
    
    wsRef.current.onclose = () => {
      if (status !== 'completed' && status !== 'failed') {
        setStatus('idle');
      }
    };
  };
  
  /**
   * 断开连接
   */
  const disconnect = () => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
  };
  
  /**
   * 重置状态
   */
  const reset = () => {
    disconnect();
    setTaskId(null);
    setStatus('idle');
    setProgress(0);
    setMessage('');
    setResult(null);
    setError(null);
  };
  
  // Cleanup on unmount
  useEffect(() => {
    return () => {
      disconnect();
    };
  }, []);
  
  return {
    taskId,
    status,
    progress,
    message,
    result,
    error,
    submitTask,
    disconnect,
    reset
  };
}
```

### 5.2 React 组件示例

```jsx
import React, { useState } from 'react';
import { useDocumentTask } from './hooks/useDocumentTask';

function DocumentUploader() {
  const [selectedFile, setSelectedFile] = useState(null);
  const {
    taskId,
    status,
    progress,
    message,
    result,
    error,
    submitTask,
    reset
  } = useDocumentTask('http://localhost:8000');
  
  const handleFileChange = (e) => {
    setSelectedFile(e.target.files[0]);
  };
  
  const handleSubmit = async () => {
    if (!selectedFile) {
      alert('请选择文件');
      return;
    }
    
    try {
      await submitTask(selectedFile, 1);
    } catch (err) {
      console.error('提交失败:', err);
    }
  };
  
  const handleReset = () => {
    setSelectedFile(null);
    reset();
  };
  
  return (
    <div className="document-uploader">
      <h2>📄 文档处理</h2>
      
      {/* 文件选择 */}
      <div className="file-input">
        <input
          type="file"
          onChange={handleFileChange}
          disabled={status === 'processing'}
        />
        {selectedFile && <span>{selectedFile.name}</span>}
      </div>
      
      {/* 提交按钮 */}
      <button
        onClick={handleSubmit}
        disabled={!selectedFile || status === 'processing'}
      >
        {status === 'processing' ? '处理中...' : '开始处理'}
      </button>
      
      {/* 任务ID */}
      {taskId && (
        <div className="task-info">
          <strong>任务ID:</strong> {taskId}
        </div>
      )}
      
      {/* 进度条 */}
      {status !== 'idle' && (
        <div className="progress-section">
          <div className="progress-bar">
            <div
              className="progress-fill"
              style={{ width: `${progress}%` }}
            >
              {progress}%
            </div>
          </div>
          
          <div className="status-badge" data-status={status}>
            {status === 'connecting' && '🔌 连接中...'}
            {status === 'connected' && '✅ 已连接'}
            {status === 'processing' && '⚙️ 处理中'}
            {status === 'completed' && '✅ 已完成'}
            {status === 'failed' && '❌ 失败'}
          </div>
          
          {message && <p className="status-message">{message}</p>}
        </div>
      )}
      
      {/* 结果显示 */}
      {result && (
        <div className="result-card">
          <h3>✅ 处理完成</h3>
          <p>处理文件数: {result.processed_files}</p>
          <p>总文件数: {result.total_files}</p>
          <p>状态: {result.status}</p>
        </div>
      )}
      
      {/* 错误显示 */}
      {error && (
        <div className="error-card">
          <h3>❌ 错误</h3>
          <p>{error}</p>
        </div>
      )}
      
      {/* 重置按钮 */}
      {(status === 'completed' || status === 'failed') && (
        <button onClick={handleReset} className="reset-button">
          重新上传
        </button>
      )}
    </div>
  );
}

export default DocumentUploader;
```

### 5.3 CSS 样式

```css
.document-uploader {
  max-width: 600px;
  margin: 0 auto;
  padding: 20px;
}

.file-input {
  margin: 20px 0;
}

button {
  padding: 12px 24px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 600;
}

button:disabled {
  background: #ccc;
  cursor: not-allowed;
}

.progress-section {
  margin: 20px 0;
}

.progress-bar {
  width: 100%;
  height: 30px;
  background: #e0e0e0;
  border-radius: 15px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #4CAF50, #8BC34A);
  transition: width 0.3s ease;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-weight: bold;
}

.status-badge {
  display: inline-block;
  padding: 8px 16px;
  border-radius: 20px;
  margin: 10px 0;
  font-weight: 600;
}

.status-badge[data-status="processing"] {
  background: #2196F3;
  color: white;
}

.status-badge[data-status="completed"] {
  background: #4CAF50;
  color: white;
}

.status-badge[data-status="failed"] {
  background: #F44336;
  color: white;
}

.result-card,
.error-card {
  padding: 20px;
  border-radius: 8px;
  margin: 20px 0;
}

.result-card {
  background: #e8f5e9;
  border: 1px solid #4CAF50;
}

.error-card {
  background: #ffebee;
  border: 1px solid #F44336;
}
```

---

## 6. Vue 集成示例

### 6.1 Composable

```javascript
// composables/useDocumentTask.js
import { ref, onUnmounted } from 'vue';

export function useDocumentTask(baseUrl = 'http://localhost:8000') {
  const taskId = ref(null);
  const status = ref('idle');
  const progress = ref(0);
  const message = ref('');
  const result = ref(null);
  const error = ref(null);
  
  let ws = null;
  
  const submitTask = async (file, instanceId = 1) => {
    const formData = new FormData();
    formData.append('files', file);
    formData.append('instance_id', instanceId);
    formData.append('chunk_size', 500);
    formData.append('chunk_overlap', 50);
    
    try {
      const response = await fetch(`${baseUrl}/api/v1/docs/process`, {
        method: 'POST',
        body: formData
      });
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      
      const data = await response.json();
      taskId.value = data.task_id;
      connectWebSocket(data.task_id);
      return data.task_id;
      
    } catch (err) {
      error.value = err.message;
      status.value = 'failed';
      throw err;
    }
  };
  
  const connectWebSocket = (id) => {
    const wsUrl = baseUrl.replace('http', 'ws') + `/api/v1/docs/ws/${id}`;
    
    status.value = 'connecting';
    ws = new WebSocket(wsUrl);
    
    ws.onopen = () => {
      status.value = 'connected';
    };
    
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      
      if (data.type === 'task_event') {
        progress.value = data.progress || 0;
        message.value = data.message || '';
        
        if (data.event_type === 'task_started' || data.event_type === 'task_progress_updated') {
          status.value = 'processing';
        } else if (data.event_type === 'task_completed') {
          status.value = 'completed';
          result.value = data.result;
        } else if (data.event_type === 'task_failed') {
          status.value = 'failed';
          error.value = data.error;
        }
      }
    };
    
    ws.onerror = () => {
      error.value = 'WebSocket connection error';
      status.value = 'failed';
    };
  };
  
  const disconnect = () => {
    if (ws) {
      ws.close();
      ws = null;
    }
  };
  
  const reset = () => {
    disconnect();
    taskId.value = null;
    status.value = 'idle';
    progress.value = 0;
    message.value = '';
    result.value = null;
    error.value = null;
  };
  
  onUnmounted(() => {
    disconnect();
  });
  
  return {
    taskId,
    status,
    progress,
    message,
    result,
    error,
    submitTask,
    disconnect,
    reset
  };
}
```

### 6.2 Vue 组件示例

```vue
<template>
  <div class="document-uploader">
    <h2>📄 文档处理</h2>
    
    <!-- 文件选择 -->
    <div class="file-input">
      <input
        type="file"
        @change="handleFileChange"
        :disabled="status === 'processing'"
      />
      <span v-if="selectedFile">{{ selectedFile.name }}</span>
    </div>
    
    <!-- 提交按钮 -->
    <button
      @click="handleSubmit"
      :disabled="!selectedFile || status === 'processing'"
    >
      {{ status === 'processing' ? '处理中...' : '开始处理' }}
    </button>
    
    <!-- 任务ID -->
    <div v-if="taskId" class="task-info">
      <strong>任务ID:</strong> {{ taskId }}
    </div>
    
    <!-- 进度条 -->
    <div v-if="status !== 'idle'" class="progress-section">
      <div class="progress-bar">
        <div class="progress-fill" :style="{ width: progress + '%' }">
          {{ progress }}%
        </div>
      </div>
      
      <div class="status-badge" :data-status="status">
        <template v-if="status === 'connecting'">🔌 连接中...</template>
        <template v-else-if="status === 'connected'">✅ 已连接</template>
        <template v-else-if="status === 'processing'">⚙️ 处理中</template>
        <template v-else-if="status === 'completed'">✅ 已完成</template>
        <template v-else-if="status === 'failed'">❌ 失败</template>
      </div>
      
      <p v-if="message" class="status-message">{{ message }}</p>
    </div>
    
    <!-- 结果显示 -->
    <div v-if="result" class="result-card">
      <h3>✅ 处理完成</h3>
      <p>处理文件数: {{ result.processed_files }}</p>
      <p>总文件数: {{ result.total_files }}</p>
      <p>状态: {{ result.status }}</p>
    </div>
    
    <!-- 错误显示 -->
    <div v-if="error" class="error-card">
      <h3>❌ 错误</h3>
      <p>{{ error }}</p>
    </div>
    
    <!-- 重置按钮 -->
    <button
      v-if="status === 'completed' || status === 'failed'"
      @click="handleReset"
      class="reset-button"
    >
      重新上传
    </button>
  </div>
</template>

<script setup>
import { ref } from 'vue';
import { useDocumentTask } from '@/composables/useDocumentTask';

const selectedFile = ref(null);
const {
  taskId,
  status,
  progress,
  message,
  result,
  error,
  submitTask,
  reset
} = useDocumentTask('http://localhost:8000');

const handleFileChange = (e) => {
  selectedFile.value = e.target.files[0];
};

const handleSubmit = async () => {
  if (!selectedFile.value) {
    alert('请选择文件');
    return;
  }
  
  try {
    await submitTask(selectedFile.value, 1);
  } catch (err) {
    console.error('提交失败:', err);
  }
};

const handleReset = () => {
  selectedFile.value = null;
  reset();
};
</script>

<style scoped>
/* 使用与 React 示例相同的 CSS */
</style>
```

---

## 7. 测试工具使用

### 7.1 使用 test_websocket.html

项目根目录下的 `test_websocket.html` 是一个独立的测试页面，无需构建即可使用。

**使用步骤：**

1. **打开测试页面**：
   ```bash
   # 直接在浏览器中打开
   firefox test_websocket.html
   # 或
   open test_websocket.html
   ```

2. **获取任务 ID**：
   
   方式A - 使用 curl：
   ```bash
   curl -X POST "http://localhost:8000/api/v1/docs/process" \
     -F "files=@example.pdf" \
     -F "instance_id=1"
   ```
   
   方式B - 使用 Apifox/Postman 发送请求

3. **输入任务 ID**：
   - 复制返回的 `task_id`
   - 粘贴到测试页面的输入框中
   - 例如：`doc_process_20260113_120530_abc12345`

4. **点击"连接 WebSocket"**

5. **观察实时更新**：
   - 进度条实时更新
   - 状态徽章变化（已连接 → 运行中 → 已完成）
   - 实时日志滚动显示
   - 任务完成后显示结果

**测试页面功能：**

✅ 实时进度条  
✅ 状态徽章  
✅ 彩色日志输出  
✅ 结果展示  
✅ 错误提示  
✅ 连接统计  

### 7.2 Chrome DevTools 调试

1. **打开开发者工具**：`F12` 或 右键 → 检查

2. **查看 Network 标签**：
   - 筛选 WS（WebSocket）
   - 查看连接状态
   - 查看收发的消息

3. **查看 Console 标签**：
   - 查看日志输出
   - 测试 WebSocket 命令

**手动测试 WebSocket：**

```javascript
// 在 Console 中直接测试
const ws = new WebSocket('ws://localhost:8000/api/v1/docs/ws/your_task_id');

ws.onopen = () => console.log('连接成功');
ws.onmessage = (e) => console.log('收到消息:', JSON.parse(e.data));
ws.onerror = (e) => console.error('错误:', e);
ws.onclose = () => console.log('连接关闭');
```

---

## 8. 错误处理

### 8.1 常见错误及解决方案

#### 错误 1: WebSocket 连接失败

**错误信息：**
```
WebSocket connection to 'ws://localhost:8000/api/v1/docs/ws/xxx' failed
```

**可能原因：**
- 服务未启动
- 任务 ID 不存在
- 端口被防火墙拦截
- CORS 策略限制

**解决方案：**
```javascript
// 添加重连逻辑
function connectWithRetry(taskId, maxRetries = 3) {
  let retries = 0;
  
  function connect() {
    const ws = new WebSocket(`ws://localhost:8000/api/v1/docs/ws/${taskId}`);
    
    ws.onerror = (error) => {
      console.error(`连接失败 (尝试 ${retries + 1}/${maxRetries})`);
      
      if (retries < maxRetries) {
        retries++;
        setTimeout(connect, 2000); // 2秒后重试
      } else {
        console.error('达到最大重试次数，放弃连接');
        // 降级到轮询方案
        fallbackToPolling(taskId);
      }
    };
    
    return ws;
  }
  
  return connect();
}
```

#### 错误 2: 任务提交失败

**错误信息：**
```
HTTP 500: Internal Server Error
```

**解决方案：**
```javascript
async function submitTaskWithErrorHandling(file) {
  try {
    const response = await fetch('/api/v1/docs/process', {
      method: 'POST',
      body: formData
    });
    
    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(errorData.detail || `HTTP ${response.status}`);
    }
    
    return await response.json();
    
  } catch (error) {
    console.error('提交任务失败:', error);
    
    // 显示用户友好的错误信息
    if (error.message.includes('Network')) {
      alert('网络连接失败，请检查网络');
    } else if (error.message.includes('500')) {
      alert('服务器内部错误，请稍后重试');
    } else {
      alert(`提交失败: ${error.message}`);
    }
    
    throw error;
  }
}
```

### 8.2 降级方案：WebSocket + 轮询

当 WebSocket 不可用时，自动降级到轮询：

```javascript
class DocumentTaskClientWithFallback {
  constructor(baseUrl) {
    this.baseUrl = baseUrl;
    this.ws = null;
    this.pollingInterval = null;
  }
  
  async monitorTask(taskId, callbacks) {
    // 尝试 WebSocket
    try {
      await this.connectWebSocket(taskId, callbacks);
    } catch (error) {
      console.warn('WebSocket 不可用，降级到轮询');
      this.startPolling(taskId, callbacks);
    }
  }
  
  connectWebSocket(taskId, callbacks) {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(`ws://${this.baseUrl}/api/v1/docs/ws/${taskId}`);
      
      ws.onopen = () => resolve();
      ws.onerror = () => reject(new Error('WebSocket 连接失败'));
      
      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'task_event') {
          this.handleEvent(data, callbacks);
        }
      };
      
      this.ws = ws;
    });
  }
  
  startPolling(taskId, callbacks) {
    this.pollingInterval = setInterval(async () => {
      try {
        const response = await fetch(`${this.baseUrl}/api/v1/docs/status/${taskId}`);
        const data = await response.json();
        
        callbacks.onProgress({
          progress: data.progress,
          message: data.message,
          status: data.status
        });
        
        if (data.status === 'completed') {
          callbacks.onCompleted({ result: data.result });
          this.stopPolling();
        } else if (data.status === 'failed') {
          callbacks.onFailed({ error: data.error });
          this.stopPolling();
        }
        
      } catch (error) {
        console.error('轮询失败:', error);
      }
    }, 1000); // 每秒轮询一次
  }
  
  stopPolling() {
    if (this.pollingInterval) {
      clearInterval(this.pollingInterval);
      this.pollingInterval = null;
    }
  }
  
  handleEvent(data, callbacks) {
    // 与 WebSocket 相同的事件处理逻辑
    // ...
  }
}
```

---

## 9. 最佳实践

### 9.1 性能优化

```javascript
// ✅ 好的做法：单例模式，复用连接
class WebSocketManager {
  constructor() {
    this.connections = new Map();
  }
  
  connect(taskId, callbacks) {
    // 如果已存在连接，直接返回
    if (this.connections.has(taskId)) {
      return this.connections.get(taskId);
    }
    
    const ws = new WebSocket(`ws://localhost:8000/api/v1/docs/ws/${taskId}`);
    this.connections.set(taskId, ws);
    
    // 设置事件监听
    // ...
    
    return ws;
  }
  
  disconnect(taskId) {
    const ws = this.connections.get(taskId);
    if (ws) {
      ws.close();
      this.connections.delete(taskId);
    }
  }
}

// 全局单例
const wsManager = new WebSocketManager();
```

### 9.2 用户体验优化

```javascript
// 添加加载动画
function showLoading(message = '处理中...') {
  const loader = document.getElementById('loader');
  loader.textContent = message;
  loader.style.display = 'block';
}

function hideLoading() {
  const loader = document.getElementById('loader');
  loader.style.display = 'none';
}

// 添加声音提示（任务完成时）
function playNotificationSound() {
  const audio = new Audio('/sounds/notification.mp3');
  audio.play();
}

// 添加浏览器通知
function showBrowserNotification(title, body) {
  if ('Notification' in window && Notification.permission === 'granted') {
    new Notification(title, { body, icon: '/icon.png' });
  }
}

// 使用示例
client.connect(taskId, {
  onCompleted: ({ result }) => {
    hideLoading();
    playNotificationSound();
    showBrowserNotification('任务完成', '文档处理已完成！');
  }
});
```

### 9.3 安全性考虑

```javascript
// 验证消息格式
function isValidTaskEvent(data) {
  return (
    data &&
    typeof data === 'object' &&
    data.type === 'task_event' &&
    typeof data.task_id === 'string' &&
    typeof data.progress === 'number' &&
    data.progress >= 0 &&
    data.progress <= 100
  );
}

ws.onmessage = (event) => {
  try {
    const data = JSON.parse(event.data);
    
    if (!isValidTaskEvent(data)) {
      console.warn('收到无效消息:', data);
      return;
    }
    
    // 处理有效消息
    handleTaskEvent(data);
    
  } catch (error) {
    console.error('解析消息失败:', error);
  }
};
```

### 9.4 调试技巧

```javascript
// 开发模式：详细日志
const DEBUG = true;

function log(level, message, data) {
  if (!DEBUG) return;
  
  const timestamp = new Date().toISOString();
  const prefix = `[${timestamp}] [${level}]`;
  
  if (data) {
    console.log(prefix, message, data);
  } else {
    console.log(prefix, message);
  }
}

// 使用
log('INFO', 'WebSocket 连接成功');
log('DEBUG', '收到消息', data);
log('ERROR', '连接失败', error);
```

---

## 10. FAQ

### Q1: WebSocket 连接会自动重连吗？

A: 默认不会自动重连。建议实现重连逻辑（参见 8.1 错误处理）。

### Q2: 一个任务可以有多个客户端同时监听吗？

A: 可以。多个客户端可以同时订阅同一个任务的进度更新。

### Q3: 任务完成后，WebSocket 会自动关闭吗？

A: 建议在收到 `task_completed` 或 `task_failed` 事件后主动关闭连接。

### Q4: 支持跨域吗？

A: WebSocket 支持跨域，但需要确保服务端配置了正确的 CORS 策略。

### Q5: 如何处理长时间运行的任务？

A: WebSocket 连接会保持打开状态。确保实现心跳机制防止超时。

---

## 11. 技术支持

### 11.1 联系方式

- **技术文档**: `/docs/观察者模式使用指南.md`
- **后端接口文档**: `http://localhost:8000/api/v1/docs`
- **问题反馈**: [Issue Tracker]

### 11.2 相关资源

- [WebSocket API - MDN](https://developer.mozilla.org/en-US/docs/Web/API/WebSocket)
- [FastAPI WebSocket](https://fastapi.tiangolo.com/advanced/websockets/)
- [观察者模式 - Design Patterns](https://refactoring.guru/design-patterns/observer)

---

📝 **文档版本**: v1.0  
📅 **更新日期**: 2026-01-13  
👥 **目标读者**: 前端开发者  
🔄 **更新频率**: 随 API 更新而更新
