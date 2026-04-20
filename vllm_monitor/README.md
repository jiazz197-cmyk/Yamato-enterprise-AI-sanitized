# vLLM Monitor - GPU & vLLM 监控系统

轻量级监控系统，专为 **4×RTX 4090 + Ubuntu Server** 优化，使用Conda环境隔离，监控vLLM Docker容器和GPU资源。

## 主要功能

- 实时监控 4×RTX 4090 的显存、温度、功耗、利用率
- 监控 vLLM 实例性能（TPS、请求队列）
- 监控 Docker 容器资源使用
- Prometheus metrics 导出（可接入Grafana）
- 智能告警系统（显存、温度、功耗超阈值）
- CSV格式历史数据记录

---

## 项目文件

```
vllm-monitor/
├── monitor.py              # 主监控程序
├── environment.yml         # Conda环境配置
├── install_conda.sh        # 一键安装脚本
├── setup_conda_env.sh      # 创建/更新环境
├── start_monitor.sh        # 启动监控
├── test_environment.py     # 环境测试工具
├── check_gpu_status.sh     # GPU状态查看
├── vllm-monitor.service    # Systemd服务配置
├── README.md               # 本文件
└── CONDA使用说明.md        # 详细使用文档
```

---

## 快速开始

### 1. 上传文件到服务器

```bash
# 从本地上传到服务器
scp -r * your-user@your-server:~/vllm-monitor/
```

### 2. 一键安装

```bash
# SSH连接到服务器
ssh your-user@your-server

# 进入目录
cd ~/vllm-monitor

# 运行安装脚本（会自动安装miniconda和创建环境）
bash install_conda.sh
```

### 3. 启动监控

```bash
# 关闭并重新打开终端（让conda初始化生效）

# 启动监控
cd ~/vllm-monitor
./start_monitor.sh

# 或手动激活环境后启动
conda activate vllm-monitor
python monitor.py
```

### 4. 验证运行

```bash
# 查看GPU状态
./check_gpu_status.sh

# 访问metrics端点
curl http://localhost:9400/metrics

# 查看日志
tail -f /var/log/monitor_vllm.log
```

---

## 监控指标

访问 `http://your-server:9400/metrics` 获取Prometheus格式的指标：

### GPU指标（每张卡）
- `gpu_memory_used_bytes` / `gpu_memory_total_bytes` - 显存使用
- `gpu_temperature_celsius` - GPU温度
- `gpu_power_draw_watts` - GPU功耗
- `gpu_utilization_percent` - GPU利用率

### vLLM指标（每个实例）
- `vllm_waiting_requests` - 排队等待的请求数
- `vllm_running_requests` - 正在处理的请求数
- `vllm_tokens_per_second` - 每秒生成token数

### 主机指标
- `host_memory_free_bytes` - 可用内存
- `host_cpu_percent` - CPU使用率
- `host_load1` - 系统负载

### Docker容器指标
- `container_memory_used_bytes` - 容器内存
- `container_cpu_percent` - 容器CPU

---

## 配置修改

编辑 `monitor.py` 中的配置区域：

```python
# vLLM实例端点（根据实际部署修改）
VLLM_INSTANCES = [
    "http://127.0.0.1:8000/metrics",
    "http://127.0.0.1:8001/metrics",
]

# Docker容器名称
DOCKER_CONTAINERS = ["qwen30b_tp2", "qwen8_gpu2", "bge_gpu3"]

# 告警阈值（针对RTX 4090优化）
THRESHOLDS = {
    "gpu_memory_used_ratio": 0.90,    # 显存使用率 >= 90%
    "gpu_temperature": 83,             # 温度 >= 83°C
    "gpu_power_watts": 420,            # 功耗 >= 420W
    "vllm_waiting_requests": 10,       # 排队请求 >= 10
    "host_free_gb": 32,                # 可用内存 < 32GB
}
```

---

## 设置开机自启动

```bash
# 1. 修改service文件中的conda路径
nano vllm-monitor.service
# 将 ExecStart 中的 /root/miniconda3 改为你的conda路径

# 2. 复制service文件
sudo cp vllm-monitor.service /etc/systemd/system/

# 3. 重载systemd
sudo systemctl daemon-reload

# 4. 启用并启动服务
sudo systemctl enable vllm-monitor
sudo systemctl start vllm-monitor

# 5. 查看状态
sudo systemctl status vllm-monitor

# 6. 查看日志
sudo journalctl -u vllm-monitor -f
```

---

## Grafana可视化

### 1. 配置Prometheus

编辑 `/etc/prometheus/prometheus.yml`：

```yaml
scrape_configs:
  - job_name: 'vllm-monitor'
    static_configs:
      - targets: ['localhost:9400']
    scrape_interval: 5s
```

重启Prometheus：
```bash
sudo systemctl restart prometheus
```

### 2. 创建Grafana Dashboard

推荐的监控面板：

**GPU显存使用率**
```promql
gpu_memory_used_bytes / gpu_memory_total_bytes * 100
```

**GPU温度对比**
```promql
gpu_temperature_celsius
```

**vLLM总TPS**
```promql
sum(vllm_tokens_per_second)
```

**主机可用内存**
```promql
host_memory_free_bytes / 1024^3
```

---

## 常用命令

```bash
# 查看实时GPU状态（彩色表格）
./check_gpu_status.sh

# 测试环境配置
python test_environment.py

# 查看metrics
curl http://localhost:9400/metrics

# 查看运行日志
tail -f /var/log/monitor_vllm.log

# 查看CSV历史数据
tail -f /var/log/monitor_vllm_metrics.csv

# 激活conda环境
conda activate vllm-monitor

# 更新conda环境
conda env update -f environment.yml --prune
```

---

## Conda环境管理

### 为什么使用Conda？
- [success] **环境隔离** - 不污染系统Python环境
- [success] **避免冲突** - 与其他项目依赖不冲突
- [success] **易于管理** - 一条命令创建/删除环境
- [success] **无权限问题** - 不需要sudo安装依赖

### 环境操作

```bash
# 查看所有环境
conda env list

# 激活环境
conda activate vllm-monitor

# 退出环境
conda deactivate

# 更新环境
conda env update -f environment.yml --prune

# 删除环境
conda env remove -n vllm-monitor

# 重建环境
conda env remove -n vllm-monitor
conda env create -f environment.yml
```

详细的Conda使用说明请查看：**[CONDA使用说明.md](CONDA使用说明.md)**

---

## 使用场景

### 场景1: 检测显存分配不均

```bash
./check_gpu_status.sh
```

如果某张GPU显存>90%，其他卡空闲：
→ 调整vLLM的tensor parallel配置

### 场景2: vLLM性能瓶颈

```bash
curl -s http://localhost:9400/metrics | grep vllm_waiting_requests
```

如果持续>10：
→ 增加GPU数量或优化batch size

### 场景3: GPU温度过高

```bash
./check_gpu_status.sh
```

如果温度>83°C：
→ 限制GPU功耗到400W：
```bash
sudo nvidia-smi -i 0,1,2,3 -pl 400
```

---

## 故障排查

### 问题1: 检测不到GPU

```bash
# 检查驱动
nvidia-smi

# 测试pynvml
conda activate vllm-monitor
python -c "import pynvml; pynvml.nvmlInit(); print('OK')"
```

### 问题2: Conda环境问题

```bash
# 重新初始化conda
~/miniconda3/bin/conda init bash
source ~/.bashrc

# 重建环境
conda env remove -n vllm-monitor
bash setup_conda_env.sh
```

### 问题3: 端口被占用

```bash
# 查找占用进程
sudo lsof -i :9400

# 杀死进程
sudo kill $(lsof -t -i:9400)
```

### 问题4: Docker监控失败

```bash
# 添加docker组权限
sudo usermod -aG docker $USER
newgrp docker
```

更多故障排查请查看：**[CONDA使用说明.md](CONDA使用说明.md)**

---

## 文档

- **[README.md](README.md)** - 本文件，快速开始指南
- **[CONDA使用说明.md](CONDA使用说明.md)** - 详细的Conda使用文档
- **[文件说明.txt](文件说明.txt)** - 文件清单和简要说明

---

## 主要改进

相比原始代码：
- [success] 修复所有已知Bug（waiting_requests取值、Windows兼容性等）
- [success] 针对4×RTX 4090优化阈值
- [success] 添加GPU功耗监控（4090重要指标）
- [success] 完善的日志系统
- [success] 优雅关闭机制
- [success] 使用Conda环境隔离
- [success] 记录所有GPU数据（不只是第一个）
- [success] 更好的错误处理和日志

---

## 获取帮助

1. 运行环境测试：`python test_environment.py`
2. 查看详细文档：`cat CONDA使用说明.md`
3. 查看监控日志：`tail -f /var/log/monitor_vllm.log`
4. 查看GPU状态：`nvidia-smi`

---

**硬件配置**: 4×NVIDIA RTX 4090 (24GB VRAM) + 2×AMD Server CPU  
**操作系统**: Ubuntu Server  
**Python版本**: 3.10 (Conda环境)  
**环境管理**: Miniconda  

祝监控顺利！
