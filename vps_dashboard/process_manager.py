import psutil
from flask import Blueprint, render_template, jsonify, request
from .utils import login_required

process_manager_bp = Blueprint('process_manager', __name__, url_prefix='/process_manager')

@process_manager_bp.route('/')
@login_required
def process_manager_index():
    return render_template('processes.html')

@process_manager_bp.route('/processes')
@login_required
def get_processes():
    """获取所有正在运行的进程信息。"""
    try:
        processes_list = []
        for proc in psutil.process_iter(['pid', 'name', 'username', 'cpu_percent', 'memory_percent', 'status', 'cmdline']):
            try:
                pinfo = proc.as_dict(attrs=['pid', 'name', 'username', 'cpu_percent', 'memory_percent', 'status', 'cmdline'])
                pinfo['cpu_percent'] = round(pinfo['cpu_percent'], 2)
                pinfo['memory_percent'] = round(pinfo['memory_percent'], 2)
                pinfo['cmdline'] = ' '.join(pinfo['cmdline']) if pinfo['cmdline'] else ''
                processes_list.append(pinfo)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        
        return jsonify({"status": "success", "processes": processes_list})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@process_manager_bp.route('/processes/kill', methods=['POST'])
@login_required
def kill_process():
    """结束指定 PID 的进程。"""
    try:
        pid = request.json.get('pid')
        if not pid:
            return jsonify({"status": "error", "message": "PID is required."}), 400
        
        try:
            p = psutil.Process(pid)
            p.terminate() # 尝试优雅地终止进程
            # p.kill() # 如果 terminate 失败，可以使用 kill 强制终止
            return jsonify({"status": "success", "message": f"进程 {pid} 已发送终止信号。"}), 200
        except psutil.NoSuchProcess:
            return jsonify({"status": "error", "message": f"进程 {pid} 不存在。"}), 404
        except psutil.AccessDenied:
            return jsonify({"status": "error", "message": f"权限不足，无法终止进程 {pid}。"}), 403
        except Exception as e:
            return jsonify({"status": "error", "message": f"终止进程 {pid} 失败: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500