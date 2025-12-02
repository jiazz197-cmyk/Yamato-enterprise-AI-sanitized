#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
monitor_vllm.py
轻量级监控 + Prometheus exporter for vLLM + LMCache + GPU + host
用途：在机器上长期运行，Prometheus 拉取 /metrics 即可获得这些指标
"""

import time
import os
import csv
import sys
import logging
import signal
import traceback
from typing import Dict, Any, List, Optional
from datetime import datetime

import requests
import psutil
from prometheus_client import start_http_server, Gauge

# 尝试导入 pynvml (GPU monitoring)
try:
    import pynvml
    NVML_AVAILABLE = True
except ImportError:
    NVML_AVAILABLE = False

# 尝试导入 docker SDK
try:
    import docker
    DOCKER_AVAILABLE = True
except ImportError:
    DOCKER_AVAILABLE = False


# ============================================================
# CONFIGURATION SECTION - 配置区域
# ============================================================
# Hardware Info: 4x RTX 4090 (24GB each) + 2x AMD Server CPUs
# OS: Ubuntu Server

POLL_INTERVAL = 5                 # 秒，采样周期
EXPORTER_PORT = 9400              # Prometheus scrape port

# vLLM / LMCache endpoints (http)
# 示例配置：根据你的实际部署调整
VLLM_INSTANCES = [
    "http://127.0.0.1:8000/metrics",   # vLLM instance 1
    # "http://127.0.0.1:8001/metrics", # vLLM instance 2
    # "http://127.0.0.1:8002/metrics", # vLLM instance 3
]
LM_CACHE_METRICS = "http://127.0.0.1:19200/metrics"  # LMCache metrics endpoint

# Docker container names to monitor
# 根据你的实际容器名称调整
DOCKER_CONTAINERS = ["qwen30b_tp2", "qwen8_gpu2", "bge_gpu3"]

# Slack alerting webhook URL (设置为 None 则只打印到控制台)
SLACK_WEBHOOK = None  # "https://hooks.slack.com/services/..." or None

# Alert thresholds - 告警阈值配置 (针对4090优化)
THRESHOLDS = {
    # RTX 4090 24GB VRAM，建议在90%时告警
    "gpu_memory_used_ratio": 0.90,       # GPU内存使用率 >= 90% 触发告警
    
    # RTX 4090 工作温度一般在70-83°C，超过83°C告警
    "gpu_temperature": 83,                # GPU温度 >= 83°C 触发告警
    
    # 4090功耗最高450W，超过420W可能需要注意
    "gpu_power_watts": 420,               # GPU功耗 >= 420W 触发告警
    
    # 服务器内存告警阈值（根据你的总内存调整）
    "host_free_gb": 32,                   # 主机可用内存 < 32GB 触发告警
    
    # vLLM性能指标
    "vllm_waiting_requests": 10,          # vLLM等待请求数 >= 10 触发告警
    
    # LMCache性能指标
    "lmcache_hit_rate": 0.65,             # LMCache命中率 < 0.65 触发告警
    
    # 容器内存告警（大模型可能需要更多内存）
    "container_memory_gb": 50,            # 容器内存使用 > 50GB 触发告警
}

# CSV log path - 日志保存路径 (Ubuntu)
CSV_LOG = "/var/log/monitor_vllm_metrics.csv"  # 生产环境路径
# CSV_LOG = "./monitor_vllm_metrics.csv"  # 开发测试用，取消注释使用

# Alert cooldown period - 告警冷却时间（避免重复告警）
ALERT_COOLDOWN = 60 * 5  # 5分钟

# Logging configuration - 日志配置
LOG_LEVEL = logging.INFO
LOG_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'
LOG_FILE = "/var/log/monitor_vllm.log"  # 日志文件路径
# LOG_FILE = "./monitor_vllm.log"  # 开发测试用，取消注释使用
# ============================================================


# 配置日志系统
logging.basicConfig(
    level=LOG_LEVEL,
    format=LOG_FORMAT,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)


# ============================================================
# PROMETHEUS METRICS DEFINITIONS - Prometheus指标定义
# ============================================================
# GPU metrics
g_gpu_mem_used = Gauge('gpu_memory_used_bytes', 'GPU memory used in bytes', ['gpu_index', 'gpu_name'])
g_gpu_mem_total = Gauge('gpu_memory_total_bytes', 'GPU memory total in bytes', ['gpu_index', 'gpu_name'])
g_gpu_util = Gauge('gpu_utilization_percent', 'GPU utilization percentage', ['gpu_index', 'gpu_name'])
g_gpu_temp = Gauge('gpu_temperature_celsius', 'GPU temperature in Celsius', ['gpu_index', 'gpu_name'])
g_gpu_power = Gauge('gpu_power_draw_watts', 'GPU power draw in Watts', ['gpu_index', 'gpu_name'])

# Host metrics
g_host_mem_free = Gauge('host_memory_free_bytes', 'Host available memory in bytes')
g_host_mem_total = Gauge('host_memory_total_bytes', 'Host total memory in bytes')
g_host_swap_used = Gauge('host_swap_used_bytes', 'Host swap used in bytes')
g_host_cpu_percent = Gauge('host_cpu_percent', 'Host CPU usage percentage')
g_host_load1 = Gauge('host_load1', 'System load average 1 minute')

# vLLM metrics
g_vllm_running = Gauge('vllm_running_requests', 'vLLM currently running requests', ['instance'])
g_vllm_waiting = Gauge('vllm_waiting_requests', 'vLLM waiting/queued requests', ['instance'])
g_vllm_tps = Gauge('vllm_tokens_per_second', 'vLLM tokens processed per second', ['instance'])
g_vllm_prefill = Gauge('vllm_prefill_time_seconds', 'vLLM prefill time in seconds', ['instance'])

# LMCache metrics
g_lmcache_hit = Gauge('lmcache_hit_rate', 'LMCache cache hit rate (0-1)')
g_lmcache_evictions = Gauge('lmcache_evictions_total', 'LMCache total evictions')

# Docker container metrics
g_container_mem = Gauge('container_memory_used_bytes', 'Container memory used in bytes', ['container'])
g_container_cpu = Gauge('container_cpu_percent', 'Container CPU usage percentage', ['container'])


# ============================================================
# HELPER FUNCTIONS - 辅助函数
# ============================================================

def parse_prometheus_text(text: str) -> Dict[str, float]:
    """
    解析Prometheus文本格式的metrics（简化版本）
    注意：如果同一指标名有多个标签组合，只会保留最后一个值
    
    Args:
        text: Prometheus文本格式的metrics
        
    Returns:
        Dict[metric_name, value]
    """
    metrics = {}
    for line in text.splitlines():
        line = line.strip()
        # 跳过空行和注释
        if not line or line.startswith('#'):
            continue
        
        parts = line.split()
        if len(parts) < 2:
            continue
            
        name_and_labels = parts[0]
        val_str = parts[1]
        
        # 尝试转换为浮点数
        try:
            value = float(val_str)
        except (ValueError, TypeError):
            logger.debug(f"Failed to parse metric value: {name_and_labels} = {val_str}")
            continue
        
        # 去除标签：取 '{' 之前的部分作为指标名
        metric_name = name_and_labels.split('{')[0]
        metrics[metric_name] = value
    
    return metrics


# ============================================================
# GPU MONITORING - GPU监控
# ============================================================

class GPUMonitor:
    """GPU监控类，使用NVML保持连接提高效率"""
    
    def __init__(self):
        self.initialized = False
        self.device_count = 0
        
        if NVML_AVAILABLE:
            try:
                pynvml.nvmlInit()
                self.device_count = pynvml.nvmlDeviceGetCount()
                self.initialized = True
                logger.info(f"NVML initialized successfully, found {self.device_count} GPU(s)")
            except Exception as e:
                logger.error(f"Failed to initialize NVML: {e}")
                self.initialized = False
    
    def get_stats(self) -> List[Dict[str, Any]]:
        """
        获取所有GPU的统计信息
        
        Returns:
            List of GPU stats dictionaries
        """
        if not self.initialized:
            return []
        
        gpu_stats = []
        try:
            for i in range(self.device_count):
                try:
                    handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                    name = pynvml.nvmlDeviceGetName(handle)
                    
                    # 处理不同pynvml版本的返回值
                    if isinstance(name, bytes):
                        name = name.decode('utf-8')
                    
                    # 获取内存信息
                    meminfo = pynvml.nvmlDeviceGetMemoryInfo(handle)
                    
                    # 获取GPU利用率（可能不支持）
                    try:
                        util = pynvml.nvmlDeviceGetUtilizationRates(handle).gpu
                    except Exception:
                        util = 0
                    
                    # 获取温度（可能不支持）
                    try:
                        temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
                    except Exception:
                        temp = 0
                    
                    # 获取功耗（可能不支持）
                    try:
                        power = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0  # mW to W
                    except Exception:
                        power = 0.0
                    
                    gpu_stats.append({
                        'index': str(i),
                        'name': name,
                        'memory_total': meminfo.total,
                        'memory_used': meminfo.used,
                        'util': util,
                        'temp': temp,
                        'power': power
                    })
                    
                except Exception as e:
                    logger.error(f"Error reading GPU {i} stats: {e}")
                    
        except Exception as e:
            logger.error(f"Error in get_gpu_stats: {e}")
        
        return gpu_stats
    
    def shutdown(self):
        """关闭NVML连接"""
        if self.initialized:
            try:
                pynvml.nvmlShutdown()
                logger.info("NVML shutdown successfully")
            except Exception as e:
                logger.error(f"Error shutting down NVML: {e}")


# ============================================================
# HOST MONITORING - 主机监控
# ============================================================

def get_host_stats() -> Dict[str, Any]:
    """
    获取主机系统统计信息
    
    Returns:
        Dict with host stats
    """
    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    cpu_percent = psutil.cpu_percent(interval=1)
    
    stats = {
        'mem_free': vm.available,
        'mem_total': vm.total,
        'swap_used': sw.used,
        'cpu_percent': cpu_percent,
        'load1': 0.0  # 默认值
    }
    
    # Windows不支持getloadavg，需要特殊处理
    try:
        load1, load5, load15 = psutil.getloadavg()
        stats['load1'] = load1
    except (AttributeError, OSError):
        # Windows或其他不支持的系统，使用CPU百分比作为替代
        stats['load1'] = cpu_percent / 100.0
        logger.debug("getloadavg not available, using cpu_percent as substitute")
    
    return stats


# ============================================================
# VLLM MONITORING - vLLM监控
# ============================================================

def get_vllm_metrics(endpoint: str) -> Dict[str, float]:
    """
    从vLLM实例获取metrics
    
    Args:
        endpoint: vLLM metrics endpoint URL
        
    Returns:
        Dict of metrics
    """
    try:
        response = requests.get(endpoint, timeout=3)
        if response.status_code != 200:
            logger.warning(f"vLLM endpoint {endpoint} returned status {response.status_code}")
            return {}
        
        metrics = parse_prometheus_text(response.text)
        logger.debug(f"Retrieved {len(metrics)} metrics from {endpoint}")
        return metrics
        
    except requests.exceptions.Timeout:
        logger.warning(f"Timeout accessing vLLM endpoint: {endpoint}")
        return {}
    except requests.exceptions.ConnectionError:
        logger.warning(f"Connection error accessing vLLM endpoint: {endpoint}")
        return {}
    except Exception as e:
        logger.error(f"Error getting vLLM metrics from {endpoint}: {e}")
        return {}


# ============================================================
# LMCACHE MONITORING - LMCache监控
# ============================================================

def get_lmcache_metrics(endpoint: str) -> Dict[str, float]:
    """
    从LMCache获取metrics
    
    Args:
        endpoint: LMCache metrics endpoint URL
        
    Returns:
        Dict of metrics
    """
    try:
        response = requests.get(endpoint, timeout=3)
        if response.status_code != 200:
            logger.warning(f"LMCache endpoint returned status {response.status_code}")
            return {}
        
        return parse_prometheus_text(response.text)
        
    except requests.exceptions.Timeout:
        logger.warning(f"Timeout accessing LMCache endpoint: {endpoint}")
        return {}
    except requests.exceptions.ConnectionError:
        logger.debug(f"LMCache endpoint not accessible: {endpoint}")
        return {}
    except Exception as e:
        logger.error(f"Error getting LMCache metrics: {e}")
        return {}


# ============================================================
# DOCKER MONITORING - Docker容器监控
# ============================================================

def get_container_stats(container_names: List[str]) -> Dict[str, Dict[str, float]]:
    """
    获取Docker容器统计信息
    
    Args:
        container_names: List of container names to monitor
        
    Returns:
        Dict[container_name, {'mem': bytes, 'cpu_percent': float}]
    """
    stats = {}
    
    if not DOCKER_AVAILABLE:
        logger.debug("Docker SDK not available")
        return stats
    
    try:
        client = docker.from_env()
        
        for name in container_names:
            try:
                container = client.containers.get(name)
                container_stats = container.stats(stream=False)
                
                # 获取内存使用
                mem_usage = container_stats.get('memory_stats', {}).get('usage', 0)
                
                # 计算CPU使用率（需要安全处理precpu_stats可能为空的情况）
                cpu_percent = 0.0
                cpu_stats = container_stats.get('cpu_stats', {})
                precpu_stats = container_stats.get('precpu_stats', {})
                
                # 确保必要的字段存在
                if (cpu_stats.get('cpu_usage') and 
                    precpu_stats.get('cpu_usage') and
                    cpu_stats.get('system_cpu_usage') and
                    precpu_stats.get('system_cpu_usage')):
                    
                    cpu_delta = (cpu_stats['cpu_usage']['total_usage'] - 
                                precpu_stats['cpu_usage']['total_usage'])
                    system_delta = (cpu_stats['system_cpu_usage'] - 
                                   precpu_stats['system_cpu_usage'])
                    
                    if system_delta > 0 and cpu_delta > 0:
                        num_cpus = len(cpu_stats['cpu_usage'].get('percpu_usage', []))
                        if num_cpus == 0:
                            num_cpus = psutil.cpu_count() or 1
                        cpu_percent = (cpu_delta / system_delta) * num_cpus * 100.0
                
                stats[name] = {
                    'mem': mem_usage,
                    'cpu_percent': cpu_percent
                }
                
            except docker.errors.NotFound:
                logger.warning(f"Container '{name}' not found")
                stats[name] = {'mem': 0, 'cpu_percent': 0.0}
            except Exception as e:
                logger.error(f"Error getting stats for container '{name}': {e}")
                stats[name] = {'mem': 0, 'cpu_percent': 0.0}
                
    except Exception as e:
        logger.error(f"Docker client error: {e}")
    
    return stats


# ============================================================
# ALERTING - 告警系统
# ============================================================

class AlertManager:
    """告警管理器，处理告警去重和发送"""
    
    def __init__(self, cooldown_seconds: int = ALERT_COOLDOWN):
        self.last_alert_timestamps: Dict[str, float] = {}
        self.cooldown = cooldown_seconds
    
    def should_alert(self, alert_key: str) -> bool:
        """
        检查是否应该发送告警（基于冷却时间）
        
        Args:
            alert_key: 告警的唯一标识
            
        Returns:
            True if should alert, False if in cooldown period
        """
        now = time.time()
        last_time = self.last_alert_timestamps.get(alert_key, 0)
        
        if now - last_time > self.cooldown:
            self.last_alert_timestamps[alert_key] = now
            return True
        return False
    
    def send_alert(self, message: str):
        """
        发送告警消息
        
        Args:
            message: 告警消息内容
        """
        logger.warning(message)
        
        if not SLACK_WEBHOOK:
            return
        
        try:
            payload = {"text": message}
            response = requests.post(SLACK_WEBHOOK, json=payload, timeout=5)
            if response.status_code != 200:
                logger.error(f"Slack alert failed with status {response.status_code}")
        except Exception as e:
            logger.error(f"Failed to send Slack alert: {e}")


# 全局告警管理器实例
alert_manager = AlertManager()


def check_thresholds_and_alert(
    gpu_stats: List[Dict[str, Any]],
    host_stats: Dict[str, Any],
    vllm_metrics_all: Dict[str, Dict[str, float]],
    lm_metrics: Dict[str, float],
    container_stats: Dict[str, Dict[str, float]]
):
    """
    检查各项指标是否超过阈值，并发送告警
    
    Args:
        gpu_stats: GPU统计信息
        host_stats: 主机统计信息
        vllm_metrics_all: vLLM实例metrics
        lm_metrics: LMCache metrics
        container_stats: 容器统计信息
    """
    
    # 1. 检查GPU内存、温度和功耗
    for gpu in gpu_stats:
        gpu_idx = gpu['index']
        gpu_name = gpu['name']
        
        # GPU内存使用率
        if gpu['memory_total'] > 0:
            mem_ratio = gpu['memory_used'] / gpu['memory_total']
            if mem_ratio >= THRESHOLDS['gpu_memory_used_ratio']:
                alert_key = f"gpu_mem_high_{gpu_idx}"
                if alert_manager.should_alert(alert_key):
                    alert_manager.send_alert(
                        f"[ALERT] GPU {gpu_idx} ({gpu_name}): "
                        f"Memory usage {mem_ratio:.1%} >= {THRESHOLDS['gpu_memory_used_ratio']:.1%}"
                    )
        
        # GPU温度
        if gpu['temp'] > 0 and gpu['temp'] >= THRESHOLDS['gpu_temperature']:
            alert_key = f"gpu_temp_high_{gpu_idx}"
            if alert_manager.should_alert(alert_key):
                alert_manager.send_alert(
                    f"[ALERT] GPU {gpu_idx} ({gpu_name}): "
                    f"Temperature {gpu['temp']}°C >= {THRESHOLDS['gpu_temperature']}°C"
                )
        
        # GPU功耗 (RTX 4090特别关注)
        if 'gpu_power_watts' in THRESHOLDS and gpu['power'] > 0:
            if gpu['power'] >= THRESHOLDS['gpu_power_watts']:
                alert_key = f"gpu_power_high_{gpu_idx}"
                if alert_manager.should_alert(alert_key):
                    alert_manager.send_alert(
                        f"[ALERT] GPU {gpu_idx} ({gpu_name}): "
                        f"Power draw {gpu['power']:.1f}W >= {THRESHOLDS['gpu_power_watts']}W"
                    )
    
    # 2. 检查主机可用内存
    free_gb = host_stats['mem_free'] / (1024 ** 3)
    if free_gb < THRESHOLDS['host_free_gb']:
        alert_key = "host_low_ram"
        if alert_manager.should_alert(alert_key):
            alert_manager.send_alert(
                f"[ALERT] Host free memory low: "
                f"{free_gb:.1f} GB < {THRESHOLDS['host_free_gb']} GB"
            )
    
    # 3. 检查vLLM等待请求数
    for instance, metrics in vllm_metrics_all.items():
        # 优先使用 waiting_requests，如果不存在则尝试其他字段
        waiting = metrics.get('waiting_requests', 0)
        
        if waiting >= THRESHOLDS['vllm_waiting_requests']:
            alert_key = f"vllm_waiting_{instance}"
            if alert_manager.should_alert(alert_key):
                alert_manager.send_alert(
                    f"[ALERT] vLLM instance {instance}: "
                    f"Waiting requests {waiting} >= {THRESHOLDS['vllm_waiting_requests']}"
                )
    
    # 4. 检查LMCache命中率
    if lm_metrics:
        hit_rate = lm_metrics.get('lmcache_hit_rate')
        if hit_rate is not None and hit_rate < THRESHOLDS['lmcache_hit_rate']:
            alert_key = "lmcache_low_hit"
            if alert_manager.should_alert(alert_key):
                alert_manager.send_alert(
                    f"[ALERT] LMCache hit rate low: "
                    f"{hit_rate:.1%} < {THRESHOLDS['lmcache_hit_rate']:.1%}"
                )
    
    # 5. 检查容器内存使用
    for container_name, cstats in container_stats.items():
        mem_gb = cstats['mem'] / (1024 ** 3)
        if mem_gb > THRESHOLDS['container_memory_gb']:
            alert_key = f"container_mem_high_{container_name}"
            if alert_manager.should_alert(alert_key):
                alert_manager.send_alert(
                    f"[ALERT] Container '{container_name}': "
                    f"Memory usage {mem_gb:.1f} GB > {THRESHOLDS['container_memory_gb']} GB"
                )


# ============================================================
# CSV LOGGING - CSV日志记录
# ============================================================

class CSVLogger:
    """CSV日志记录器，支持多GPU记录"""
    
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.initialized = False
        
        # CSV表头
        self.header = [
            'timestamp',
            'datetime',
            'gpu_index',
            'gpu_name',
            'gpu_mem_used_bytes',
            'gpu_mem_total_bytes',
            'gpu_mem_ratio',
            'gpu_util_percent',
            'gpu_temp_celsius',
            'gpu_power_watts',
            'host_mem_free_bytes',
            'host_swap_used_bytes',
            'host_cpu_percent',
            'host_load1'
        ]
        
        self._init_csv()
    
    def _init_csv(self):
        """初始化CSV文件（如果不存在则创建）"""
        if not self.filepath:
            return
        
        try:
            # 如果文件不存在，创建并写入表头
            if not os.path.exists(self.filepath):
                with open(self.filepath, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(self.header)
                logger.info(f"Created CSV log file: {self.filepath}")
            
            self.initialized = True
            
        except PermissionError:
            logger.error(f"Permission denied: Cannot write to {self.filepath}")
        except Exception as e:
            logger.error(f"Failed to initialize CSV log: {e}")
    
    def log(self, gpu_stats: List[Dict], host_stats: Dict):
        """
        记录所有GPU和主机的数据到CSV
        
        Args:
            gpu_stats: GPU统计信息列表
            host_stats: 主机统计信息
        """
        if not self.initialized or not self.filepath:
            return
        
        try:
            with open(self.filepath, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                timestamp = int(time.time())
                dt_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
                # 为每个GPU写入一行
                for gpu in gpu_stats:
                    mem_ratio = (gpu['memory_used'] / gpu['memory_total'] 
                                if gpu['memory_total'] > 0 else 0)
                    
                    row = [
                        timestamp,
                        dt_str,
                        gpu['index'],
                        gpu['name'],
                        gpu['memory_used'],
                        gpu['memory_total'],
                        f"{mem_ratio:.4f}",
                        gpu['util'],
                        gpu['temp'],
                        gpu['power'],
                        host_stats['mem_free'],
                        host_stats['swap_used'],
                        host_stats['cpu_percent'],
                        host_stats['load1']
                    ]
                    writer.writerow(row)
                    
        except Exception as e:
            logger.error(f"Failed to write CSV log: {e}")


# ============================================================
# MAIN MONITOR LOOP - 主监控循环
# ============================================================

# 优雅关闭标志
shutdown_flag = False

def signal_handler(signum, frame):
    """信号处理器，用于优雅关闭"""
    global shutdown_flag
    logger.info(f"Received signal {signum}, shutting down gracefully...")
    shutdown_flag = True


def monitor_loop():
    """主监控循环"""
    global shutdown_flag
    
    # 注册信号处理器（优雅关闭）
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info("="*60)
    logger.info("Starting vLLM Monitor for Ubuntu Server")
    logger.info("Expected Hardware: 4x RTX 4090 + 2x AMD Server CPU")
    logger.info("="*60)
    logger.info(f"Poll interval: {POLL_INTERVAL}s")
    logger.info(f"Exporter port: {EXPORTER_PORT}")
    logger.info(f"CSV log: {CSV_LOG}")
    logger.info(f"Log file: {LOG_FILE}")
    logger.info(f"NVML available: {NVML_AVAILABLE}")
    logger.info(f"Docker available: {DOCKER_AVAILABLE}")
    
    # 启动Prometheus HTTP服务器
    try:
        start_http_server(EXPORTER_PORT)
        logger.info(f"✓ Prometheus exporter started on http://0.0.0.0:{EXPORTER_PORT}/metrics")
    except Exception as e:
        logger.error(f"Failed to start Prometheus exporter: {e}")
        return
    
    # 初始化GPU监控器
    gpu_monitor = GPUMonitor()
    
    # 检测并显示GPU信息
    if gpu_monitor.initialized:
        initial_gpu_stats = gpu_monitor.get_stats()
        logger.info(f"Detected {len(initial_gpu_stats)} GPU(s):")
        for gpu in initial_gpu_stats:
            mem_gb = gpu['memory_total'] / (1024**3)
            logger.info(f"  - GPU {gpu['index']}: {gpu['name']} ({mem_gb:.1f} GB VRAM)")
    else:
        logger.warning("GPU monitoring not available (NVML initialization failed)")
    
    # 初始化CSV日志记录器
    csv_logger = CSVLogger(CSV_LOG)
    
    logger.info("Starting monitoring loop...")
    logger.info("="*60)
    
    iteration = 0
    
    try:
        while not shutdown_flag:
            iteration += 1
            start_time = time.time()
            
            try:
                # ========== 1. 收集GPU指标 ==========
                gpu_stats = gpu_monitor.get_stats()
                for gpu in gpu_stats:
                    g_gpu_mem_used.labels(gpu['index'], gpu['name']).set(gpu['memory_used'])
                    g_gpu_mem_total.labels(gpu['index'], gpu['name']).set(gpu['memory_total'])
                    g_gpu_util.labels(gpu['index'], gpu['name']).set(gpu['util'])
                    g_gpu_temp.labels(gpu['index'], gpu['name']).set(gpu['temp'])
                    g_gpu_power.labels(gpu['index'], gpu['name']).set(gpu['power'])
                
                # ========== 2. 收集主机指标 ==========
                host_stats = get_host_stats()
                g_host_mem_free.set(host_stats['mem_free'])
                g_host_mem_total.set(host_stats['mem_total'])
                g_host_swap_used.set(host_stats['swap_used'])
                g_host_cpu_percent.set(host_stats['cpu_percent'])
                g_host_load1.set(host_stats['load1'])
                
                # ========== 3. 收集vLLM指标 ==========
                vllm_metrics_all = {}
                for endpoint in VLLM_INSTANCES:
                    metrics = get_vllm_metrics(endpoint)
                    vllm_metrics_all[endpoint] = metrics
                    
                    # 提取关键指标并更新Prometheus
                    running = metrics.get('vllm_num_requests_running', 
                             metrics.get('running_requests', 0))
                    waiting = metrics.get('vllm_num_requests_waiting',
                             metrics.get('waiting_requests', 0))
                    tps = metrics.get('vllm_generation_tokens_total',
                         metrics.get('tokens_per_second', 0))
                    prefill = metrics.get('vllm_time_to_first_token_seconds',
                             metrics.get('prefill_time', 0))
                    
                    g_vllm_running.labels(endpoint).set(running)
                    g_vllm_waiting.labels(endpoint).set(waiting)
                    g_vllm_tps.labels(endpoint).set(tps)
                    g_vllm_prefill.labels(endpoint).set(prefill)
                
                # ========== 4. 收集LMCache指标 ==========
                lm_metrics = {}
                if LM_CACHE_METRICS:
                    lm_metrics = get_lmcache_metrics(LM_CACHE_METRICS)
                    if lm_metrics:
                        # LMCache命中率
                        if 'lmcache_hit_rate' in lm_metrics:
                            g_lmcache_hit.set(lm_metrics['lmcache_hit_rate'])
                        
                        # LMCache驱逐计数
                        eviction_count = (lm_metrics.get('lmcache_eviction_total') or
                                        lm_metrics.get('lmcache_eviction_count') or 0)
                        g_lmcache_evictions.set(eviction_count)
                
                # ========== 5. 收集Docker容器指标 ==========
                container_stats = get_container_stats(DOCKER_CONTAINERS)
                for container_name, cstats in container_stats.items():
                    g_container_mem.labels(container_name).set(cstats['mem'])
                    g_container_cpu.labels(container_name).set(cstats['cpu_percent'])
                
                # ========== 6. 检查阈值并告警 ==========
                check_thresholds_and_alert(
                    gpu_stats, 
                    host_stats, 
                    vllm_metrics_all, 
                    lm_metrics, 
                    container_stats
                )
                
                # ========== 7. 记录到CSV ==========
                csv_logger.log(gpu_stats, host_stats)
                
                # ========== 8. 定期输出摘要 ==========
                if iteration % 12 == 0:  # 每60秒输出一次（假设POLL_INTERVAL=5）
                    # 汇总GPU信息
                    gpu_summary = []
                    for gpu in gpu_stats:
                        mem_ratio = (gpu['memory_used'] / gpu['memory_total'] * 100 
                                    if gpu['memory_total'] > 0 else 0)
                        gpu_summary.append(
                            f"GPU{gpu['index']}({mem_ratio:.0f}%, {gpu['temp']}°C, {gpu['power']:.0f}W)"
                        )
                    
                    logger.info(f"[Iter {iteration}] {' | '.join(gpu_summary)} | "
                              f"Host: {host_stats['mem_free']/(1024**3):.1f}GB free, "
                              f"CPU: {host_stats['cpu_percent']:.1f}% | "
                              f"vLLM: {len(vllm_metrics_all)} instances | "
                              f"Containers: {len(container_stats)}")
                
            except Exception as e:
                logger.error(f"Error in monitoring loop iteration {iteration}:")
                logger.error(traceback.format_exc())
            
            # 等待下一个采样周期
            elapsed = time.time() - start_time
            sleep_time = max(0, POLL_INTERVAL - elapsed)
            time.sleep(sleep_time)
    
    finally:
        # 清理资源
        logger.info("Shutting down monitor...")
        gpu_monitor.shutdown()
        logger.info("Monitor stopped")


# ============================================================
# ENTRY POINT - 程序入口
# ============================================================

if __name__ == "__main__":
    try:
        monitor_loop()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        logger.error(traceback.format_exc())
        sys.exit(1)
