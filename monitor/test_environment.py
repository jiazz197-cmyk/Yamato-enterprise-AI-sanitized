#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Environment Test Script for vLLM Monitor
Run this to verify your system configuration before starting the monitor
"""

import sys

def test_python_version():
    """Test Python version"""
    print("🔍 Testing Python version...")
    version = sys.version_info
    print(f"   Python {version.major}.{version.minor}.{version.micro}")
    if version.major >= 3 and version.minor >= 7:
        print("   ✅ PASS: Python 3.7+ detected")
        return True
    else:
        print("   ❌ FAIL: Python 3.7+ required")
        return False

def test_packages():
    """Test required packages"""
    print("\n🔍 Testing required packages...")
    packages = {
        'psutil': 'System monitoring',
        'requests': 'HTTP requests',
        'prometheus_client': 'Prometheus metrics',
        'pynvml': 'NVIDIA GPU monitoring',
        'docker': 'Docker container monitoring'
    }
    
    all_ok = True
    for pkg, desc in packages.items():
        try:
            __import__(pkg)
            print(f"   ✅ {pkg:20s} - {desc}")
        except ImportError:
            print(f"   ❌ {pkg:20s} - {desc} (NOT INSTALLED)")
            all_ok = False
    
    if not all_ok:
        print("\n   Install missing packages with:")
        print("   pip3 install -r requirements.txt")
    
    return all_ok

def test_nvidia_gpu():
    """Test NVIDIA GPU detection"""
    print("\n🔍 Testing NVIDIA GPU detection...")
    try:
        import pynvml
        pynvml.nvmlInit()
        device_count = pynvml.nvmlDeviceGetCount()
        print(f"   ✅ Detected {device_count} GPU(s):")
        
        for i in range(device_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode('utf-8')
            
            meminfo = pynvml.nvmlDeviceGetMemoryInfo(handle)
            mem_total_gb = meminfo.total / (1024**3)
            
            try:
                temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
                temp_str = f"{temp}°C"
            except:
                temp_str = "N/A"
            
            print(f"      GPU {i}: {name} ({mem_total_gb:.1f} GB) - Temp: {temp_str}")
        
        pynvml.nvmlShutdown()
        
        if device_count == 4:
            print("   ✅ PERFECT: 4 GPUs detected (as expected)")
        elif device_count > 0:
            print(f"   ⚠️  WARNING: Expected 4 GPUs, found {device_count}")
        
        return True
        
    except Exception as e:
        print(f"   ❌ FAIL: {e}")
        print("   Make sure NVIDIA driver and nvidia-ml-py are installed")
        return False

def test_docker():
    """Test Docker access"""
    print("\n🔍 Testing Docker access...")
    try:
        import docker
        client = docker.from_env()
        containers = client.containers.list()
        print(f"   ✅ Docker accessible, found {len(containers)} running container(s)")
        
        for container in containers[:5]:  # Show first 5
            name = container.name
            status = container.status
            print(f"      - {name} ({status})")
        
        if len(containers) > 5:
            print(f"      ... and {len(containers) - 5} more")
        
        return True
        
    except Exception as e:
        print(f"   ⚠️  WARNING: Docker not accessible ({e})")
        print("   If you need Docker monitoring:")
        print("   - Add your user to docker group: sudo usermod -aG docker $USER")
        print("   - Then logout and login again")
        return False

def test_port():
    """Test if port 9400 is available"""
    print("\n🔍 Testing port 9400 availability...")
    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(('localhost', 9400))
        sock.close()
        
        if result == 0:
            print("   ⚠️  WARNING: Port 9400 is already in use")
            print("   Stop the existing service or change EXPORTER_PORT in monitor.py")
            return False
        else:
            print("   ✅ Port 9400 is available")
            return True
            
    except Exception as e:
        print(f"   ⚠️  Could not test port: {e}")
        return False

def test_system_info():
    """Display system information"""
    print("\n🔍 System Information:")
    try:
        import psutil
        
        # CPU
        cpu_count = psutil.cpu_count(logical=False)
        cpu_threads = psutil.cpu_count(logical=True)
        cpu_freq = psutil.cpu_freq()
        print(f"   CPU: {cpu_count} cores, {cpu_threads} threads", end="")
        if cpu_freq:
            print(f" @ {cpu_freq.current:.0f} MHz")
        else:
            print()
        
        # Memory
        mem = psutil.virtual_memory()
        mem_total_gb = mem.total / (1024**3)
        mem_avail_gb = mem.available / (1024**3)
        print(f"   Memory: {mem_total_gb:.1f} GB total, {mem_avail_gb:.1f} GB available ({mem.percent}% used)")
        
        # Swap
        swap = psutil.swap_memory()
        swap_total_gb = swap.total / (1024**3)
        if swap_total_gb > 0:
            print(f"   Swap: {swap_total_gb:.1f} GB total ({swap.percent}% used)")
        else:
            print("   Swap: Not configured")
        
        # Load average (Linux only)
        try:
            load1, load5, load15 = psutil.getloadavg()
            print(f"   Load Average: {load1:.2f} (1m), {load5:.2f} (5m), {load15:.2f} (15m)")
        except (AttributeError, OSError):
            print("   Load Average: Not available on this system")
        
        return True
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False

def test_write_permissions():
    """Test write permissions for log files"""
    print("\n🔍 Testing write permissions...")
    test_paths = [
        "/var/log/monitor_vllm_metrics.csv",
        "/var/log/monitor_vllm.log"
    ]
    
    all_ok = True
    for path in test_paths:
        try:
            with open(path, 'a') as f:
                pass
            print(f"   ✅ Can write to {path}")
        except PermissionError:
            print(f"   ⚠️  No write permission for {path}")
            print(f"      Run with sudo or change path in monitor.py")
            all_ok = False
        except Exception as e:
            print(f"   ⚠️  Cannot write to {path}: {e}")
            all_ok = False
    
    if not all_ok:
        print("\n   Alternatively, use local paths (edit monitor.py):")
        print('   CSV_LOG = "./monitor_vllm_metrics.csv"')
        print('   LOG_FILE = "./monitor_vllm.log"')
    
    return all_ok

def main():
    """Run all tests"""
    print("="*60)
    print("🧪 vLLM Monitor - Environment Test")
    print("="*60)
    
    results = {}
    
    results['python'] = test_python_version()
    results['packages'] = test_packages()
    results['gpu'] = test_nvidia_gpu()
    results['docker'] = test_docker()
    results['port'] = test_port()
    results['system'] = test_system_info()
    results['permissions'] = test_write_permissions()
    
    # Summary
    print("\n" + "="*60)
    print("📊 Test Summary")
    print("="*60)
    
    critical_tests = ['python', 'packages', 'gpu']
    optional_tests = ['docker', 'port', 'permissions']
    
    critical_passed = all(results[t] for t in critical_tests if t in results)
    optional_passed = sum(results[t] for t in optional_tests if t in results)
    
    if critical_passed:
        print("✅ All critical tests PASSED")
        print(f"   {optional_passed}/{len(optional_tests)} optional tests passed")
        print("\n🚀 You can now run the monitor:")
        print("   ./start_monitor.sh")
        print("   or")
        print("   python3 monitor.py")
    else:
        print("❌ Some critical tests FAILED")
        print("   Please fix the issues above before running the monitor")
        sys.exit(1)
    
    print("="*60)

if __name__ == "__main__":
    main()

