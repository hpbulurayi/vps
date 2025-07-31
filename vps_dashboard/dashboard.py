import platform
import psutil
import datetime
from flask import Blueprint, render_template, jsonify
from .utils import login_required

dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')

@dashboard_bp.route('/')
@login_required
def dashboard_index():
    return render_template('dashboard.html')

@dashboard_bp.route('/system_info')
@login_required
def get_system_info():
    """获取系统信息和资源使用情况。"""
    try:
        # 系统信息
        system_info = {
            "os": platform.system(),
            "os_release": platform.release(),
            "os_version": platform.version(),
            "hostname": platform.node(),
            "uptime": datetime.timedelta(seconds=psutil.boot_time()).__str__().split('.')[0] # 运行时间
        }

        # CPU
        cpu_percent = psutil.cpu_percent(interval=None, percpu=True) # 每个核心的占用率
        cpu_overall = psutil.cpu_percent(interval=None) # 总体占用率

        # 内存
        memory = psutil.virtual_memory()
        memory_info = {
            "total": memory.total,
            "available": memory.available,
            "percent": memory.percent,
            "used": memory.used,
            "free": memory.free
        }

        # 磁盘 (只获取根分区，可扩展)
        disk_partitions = []
        for partition in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(partition.mountpoint)
                disk_partitions.append({
                    "device": partition.device,
                    "mountpoint": partition.mountpoint,
                    "total": usage.total,
                    "used": usage.used,
                    "free": usage.free,
                    "percent": usage.percent
                })
            except Exception:
                continue # 某些分区可能无法访问

        # 网络流量 (自上次调用以来的增量)
        net_io = psutil.net_io_counters()
        network_info = {
            "bytes_sent": net_io.bytes_sent,
            "bytes_recv": net_io.bytes_recv
        }
        
        return jsonify({
            "status": "success",
            "system": system_info,
            "cpu": {"overall": cpu_overall, "percpu": cpu_percent},
            "memory": memory_info,
            "disk": disk_partitions,
            "network": network_info
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500