import os
import sys
import shutil
import datetime
import functools
import platform
import psutil
import rapidjson as json
import stat
import zipfile
import tarfile
import subprocess
import re
import getpass # 导入 getpass 模块以获取当前用户名
from flask import Flask, render_template, jsonify, request, send_from_directory, redirect, url_for, session, Blueprint
from flask_socketio import SocketIO, emit
from werkzeug.utils import secure_filename

app = Flask(__name__, template_folder='templates')
app.config['SECRET_KEY'] = 'your_super_secret_key_here' # SocketIO 需要 SECRET_KEY
socketio = SocketIO(app, async_mode='eventlet')

# --- 配置 ---
# 可通过环境变量设置文件管理器的根目录，默认为当前脚本目录下的 'managed_files'
FILE_MANAGER_ROOT = os.getenv('FILE_MANAGER_ROOT', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'managed_files'))
# 确保根目录存在
os.makedirs(FILE_MANAGER_ROOT, exist_ok=True)

# --- 动态配置 systemd 路径和命令 ---
CURRENT_USER = getpass.getuser()
if CURRENT_USER == 'root':
    SYSTEMD_PATH = '/etc/systemd/system'
    SYSTEMCTL_COMMAND = ['systemctl']
else:
    SYSTEMD_PATH = os.path.expanduser('~/.config/systemd/user')
    SYSTEMCTL_COMMAND = ['systemctl', '--user']

# 认证凭据 (生产环境请勿硬编码，应从安全配置加载)
USERS = {
    "admin": "password123" 
}

# --- 辅助函数 ---
def login_required(view):
    """用于保护路由的装饰器，要求用户已登录。"""
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return view(**kwargs)
    return wrapped_view

def _get_safe_path(req_path, base_dir=FILE_MANAGER_ROOT, check_exists=False, is_dir=False, check_file=False):
    """
    安全地获取并验证文件路径。
    确保所有操作都在指定的 base_dir 范围内。
    """
    full_path = os.path.abspath(os.path.join(base_dir, req_path))

    # 安全检查：确保请求的路径在 base_dir 目录下
    if not full_path.startswith(base_dir):
        return None, (jsonify({"status": "error", "message": "Access denied."}), 403)

    if check_exists and not os.path.exists(full_path):
        return None, (jsonify({"status": "error", "message": "Path does not exist."}), 404)
        
    if is_dir and not os.path.isdir(full_path):
         return None, (jsonify({"status": "error", "message": "Path is not a directory."}), 400)
    
    if check_file and not os.path.isfile(full_path):
        return None, (jsonify({"status": "error", "message": "Path is not a file."}), 400)

    return full_path, None

def run_systemctl_command(command_parts):
    """安全地执行 systemctl 命令并返回结果。"""
    full_command = SYSTEMCTL_COMMAND + command_parts
    try:
        result = subprocess.run(full_command, capture_output=True, text=True, encoding='utf-8', check=False) # check=False to handle non-zero exits
        if result.returncode != 0:
             # 对于某些命令（如 stop 一个已经停止的服务），非零退出码是正常的
             return {"status": "warning", "stdout": result.stdout, "stderr": result.stderr, "code": result.returncode}
        return {"status": "success", "stdout": result.stdout, "stderr": result.stderr}
    except FileNotFoundError:
        return {"status": "error", "message": "systemctl command not found."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# --- 认证路由 ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username in USERS and USERS[username] == password:
            session['logged_in'] = True
            return redirect(url_for('dashboard.dashboard_index')) # 登录成功重定向到仪表盘
        else:
            return render_template('login.html', error='Invalid credentials')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

# --- 蓝图定义 ---
dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')
file_manager_bp = Blueprint('file_manager', __name__, url_prefix='/file_manager')
process_manager_bp = Blueprint('process_manager', __name__, url_prefix='/process_manager')
terminal_bp = Blueprint('terminal', __name__, url_prefix='/terminal')
systemd_manager_bp = Blueprint('systemd_manager', __name__, url_prefix='/systemd_manager')

# --- 主路由重定向 ---
@app.route('/')
@login_required
def index():
    return redirect(url_for('dashboard.dashboard_index'))

# --- 仪表盘蓝图路由 ---
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

# --- 文件管理器蓝图路由 ---
@file_manager_bp.route('/')
@login_required
def file_manager_index():
    return render_template('file_manager.html')

@file_manager_bp.route('/files')
@login_required
def list_files():
    """列出指定目录下的文件和文件夹，并包含详细信息。"""
    try:
        req_path = request.args.get('path', '')
        full_path, error_response = _get_safe_path(req_path, check_exists=True, is_dir=True)
        if error_response:
            return error_response

        items = []
        for item in os.listdir(full_path):
            item_path = os.path.join(full_path, item)
            stat_info = os.stat(item_path) # 获取文件状态信息
            is_dir = os.path.isdir(item_path)
            
            # 计算相对路径，并规范化斜杠
            relative_item_path = os.path.relpath(item_path, FILE_MANAGER_ROOT).replace("\\", "/")

            items.append({
                "name": item,
                "type": "directory" if is_dir else "file",
                "path": relative_item_path,
                "size": stat_info.st_size,
                "last_modified": datetime.datetime.fromtimestamp(stat_info.st_mtime).isoformat(),
                "permissions": oct(stat_info.st_mode & 0o777) # 获取并转换为八进制权限
            })
        
        # 添加上一级目录
        if full_path != FILE_MANAGER_ROOT:
            parent_path = os.path.dirname(req_path)
            items.insert(0, {
                "name": "..",
                "type": "directory",
                "path": parent_path.replace("\\", "/"),
                "size": None,
                "last_modified": None,
                "permissions": None
            })

        return jsonify(items)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@file_manager_bp.route('/files/download')
@login_required
def download_file():
    """下载指定的文件。"""
    try:
        req_path = request.args.get('path', '')
        full_path, error_response = _get_safe_path(req_path, check_exists=True, check_file=True)
        if error_response:
            return error_response

        return send_from_directory(os.path.dirname(full_path), os.path.basename(full_path), as_attachment=True)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@file_manager_bp.route('/files/delete', methods=['POST'])
@login_required
def delete_file():
    """删除指定的文件或文件夹。"""
    try:
        req_path = request.json.get('path', '')
        if not req_path:
            return jsonify({"status": "error", "message": "Path is required."}), 400

        full_path, error_response = _get_safe_path(req_path, check_exists=True)
        if error_response:
            return error_response

        if os.path.isfile(full_path):
            os.remove(full_path)
        elif os.path.isdir(full_path):
            shutil.rmtree(full_path)
        
        return jsonify({"status": "success", "message": f"Successfully deleted {req_path}"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@file_manager_bp.route('/files/upload', methods=['POST'])
@login_required
def upload_file():
    """上传文件到指定目录。"""
    try:
        if 'file' not in request.files:
            return jsonify({"status": "error", "message": "No file part"}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({"status": "error", "message": "No selected file"}), 400
        req_path = request.form.get('path', '')
        full_path, error_response = _get_safe_path(req_path, check_exists=True, is_dir=True)
        if error_response:
            return error_response

        if file:
            filename = secure_filename(file.filename)
            file.save(os.path.join(full_path, filename))
            return jsonify({"status": "success", "message": f"File {filename} uploaded successfully to {req_path}"})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@file_manager_bp.route('/files/create_folder', methods=['POST'])
@login_required
def create_folder():
    """创建新文件夹。"""
    try:
        req_path = request.json.get('path', '')
        if not req_path:
            return jsonify({"status": "error", "message": "Path is required."}), 400
            
        full_path, error_response = _get_safe_path(req_path)
        if error_response:
            return error_response

        if os.path.exists(full_path):
            return jsonify({"status": "error", "message": "Path already exists."}), 400

        os.makedirs(full_path)
        return jsonify({"status": "success", "message": f"Folder '{req_path}' created successfully."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@file_manager_bp.route('/files/rename', methods=['POST'])
@login_required
def rename_file():
    """重命名文件或文件夹。"""
    try:
        old_path_rel = request.json.get('old_path', '')
        new_path_rel = request.json.get('new_path', '')

        if not old_path_rel or not new_path_rel:
            return jsonify({"status": "error", "message": "Old and new paths are required."}), 400

        old_full_path, error_response = _get_safe_path(old_path_rel, check_exists=True)
        if error_response:
            return error_response
            
        new_full_path, error_response = _get_safe_path(new_path_rel)
        if error_response:
            return error_response

        if os.path.exists(new_full_path):
            return jsonify({"status": "error", "message": "New path already exists."}), 400
        
        os.rename(old_full_path, new_full_path)
        return jsonify({"status": "success", "message": f"Renamed '{old_path_rel}' to '{new_path_rel}'."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@file_manager_bp.route('/files/get_content', methods=['GET'])
@login_required
def get_file_content():
    """获取文本文件内容。"""
    try:
        req_path = request.args.get('path', '')
        full_path, error_response = _get_safe_path(req_path, check_exists=True, check_file=True)
        if error_response:
            return error_response
        
        # 尝试以UTF-8读取，如果失败则尝试其他编码
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except UnicodeDecodeError:
            # 尝试其他常见编码
            try:
                with open(full_path, 'r', encoding='latin-1') as f:
                    content = f.read()
            except Exception:
                return jsonify({"status": "error", "message": "无法解码文件内容，请尝试其他方式。"}), 500

        return jsonify({"status": "success", "content": content})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@file_manager_bp.route('/files/save_content', methods=['POST'])
@login_required
def save_file_content():
    """保存文本文件内容。"""
    try:
        req_path = request.json.get('path', '')
        content = request.json.get('content', '')
        
        full_path, error_response = _get_safe_path(req_path)
        if error_response:
            return error_response
            
        # 如果文件不存在，则创建父目录
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return jsonify({"status": "success", "message": f"文件 '{req_path}' 保存成功。"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@file_manager_bp.route('/files/permissions', methods=['GET', 'POST'])
@login_required
def handle_permissions():
    """获取或设置文件/文件夹权限。"""
    try:
        req_path = request.args.get('path') if request.method == 'GET' else request.json.get('path')
        if not req_path:
            return jsonify({"status": "error", "message": "Path is required."}), 400

        full_path, error_response = _get_safe_path(req_path, check_exists=True)
        if error_response:
            return error_response

        if request.method == 'GET':
            # 获取权限
            current_mode = os.stat(full_path).st_mode
            octal_permission = oct(current_mode & 0o777)
            return jsonify({"status": "success", "path": req_path, "permissions": octal_permission})
        elif request.method == 'POST':
            # 设置权限
            new_permission_octal = request.json.get('permissions')
            if not new_permission_octal:
                return jsonify({"status": "error", "message": "Permissions are required."}), 400
            
            try:
                # 将八进制字符串转换为整数
                mode_int = int(new_permission_octal, 8)
                os.chmod(full_path, mode_int)
                return jsonify({"status": "success", "message": f"权限已更新为 {new_permission_octal}。"}), 200
            except ValueError:
                return jsonify({"status": "error", "message": "无效的权限格式。请提供有效的八进制数 (例如 755)。"}), 400
            except Exception as e:
                return jsonify({"status": "error", "message": f"设置权限失败: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@file_manager_bp.route('/files/compress', methods=['POST'])
@login_required
def compress_file_or_folder():
    """压缩文件或文件夹。"""
    try:
        req_path = request.json.get('path', '')
        archive_format = request.json.get('format', 'zip') # 默认为zip
        
        if not req_path:
            return jsonify({"status": "error", "message": "Path is required."}), 400

        full_path, error_response = _get_safe_path(req_path, check_exists=True)
        if error_response:
            return error_response

        output_filename = os.path.basename(full_path)
        output_dir = os.path.dirname(full_path)

        if os.path.isfile(full_path):
            if archive_format == 'zip':
                archive_name = os.path.join(output_dir, f"{output_filename}.zip")
                with zipfile.ZipFile(archive_name, 'w', zipfile.ZIP_DEFLATED) as zf:
                    zf.write(full_path, os.path.basename(full_path))
            elif archive_format == 'tar.gz':
                archive_name = os.path.join(output_dir, f"{output_filename}.tar.gz")
                with tarfile.open(archive_name, "w:gz") as tar:
                    tar.add(full_path, arcname=os.path.basename(full_path))
            else:
                return jsonify({"status": "error", "message": "不支持的压缩格式。"}), 400
        elif os.path.isdir(full_path):
            if archive_format == 'zip':
                archive_name = os.path.join(output_dir, output_filename)
                shutil.make_archive(archive_name, 'zip', full_path)
                archive_name = f"{output_filename}.zip"
            elif archive_format == 'tar.gz':
                archive_name = os.path.join(output_dir, output_filename)
                shutil.make_archive(archive_name, 'gztar', full_path)
                archive_name = f"{output_filename}.tar.gz"
            else:
                return jsonify({"status": "error", "message": "不支持的压缩格式。"}), 400
        else:
            return jsonify({"status": "error", "message": "无法压缩非文件或文件夹的路径。"}), 400
        
        return jsonify({"status": "success", "message": f"'{req_path}' 已成功压缩为 '{os.path.basename(archive_name)}'。"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@file_manager_bp.route('/files/decompress', methods=['POST'])
@login_required
def decompress_file():
    """解压文件。"""
    try:
        req_path = request.json.get('path', '')
        destination = request.json.get('destination', '') # 解压目标路径
        
        if not req_path:
            return jsonify({"status": "error", "message": "Path is required."}), 400

        full_path, error_response = _get_safe_path(req_path, check_exists=True, check_file=True)
        if error_response:
            return error_response

        # 确定解压目标路径
        if destination:
            full_destination, error_response = _get_safe_path(destination, check_exists=True, is_dir=True)
            if error_response:
                return error_response
        else:
            full_destination = os.path.dirname(full_path) # 默认为同级目录

        # 确保目标路径存在
        os.makedirs(full_destination, exist_ok=True)

        if zipfile.is_zipfile(full_path):
            with zipfile.ZipFile(full_path, 'r') as zf:
                zf.extractall(full_destination)
        elif tarfile.is_tarfile(full_path):
            with tarfile.open(full_path, 'r:*') as tar:
                tar.extractall(full_destination)
        else:
            return jsonify({"status": "error", "message": "不支持的解压文件格式。"}), 400
        
        return jsonify({"status": "success", "message": f"'{req_path}' 已成功解压到 '{destination if destination else os.path.basename(full_destination)}'。"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- 进程管理蓝图路由 ---
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

# --- Web 终端蓝图路由 ---
@terminal_bp.route('/')
@login_required
def terminal_index():
    return render_template('terminal.html')

@socketio.on('connect', namespace='/terminal')
def terminal_connect():
    if 'logged_in' not in session:
        return False # 拒绝未认证的连接
    print('Web-Terminal Client connected')
    emit('response', {'data': '*** Welcome to VPS-Lite-Dashboard Web Terminal ***\n'})

@socketio.on('disconnect', namespace='/terminal')
def terminal_disconnect():
    print('Web-Terminal Client disconnected')

@socketio.on('execute_command', namespace='/terminal')
def handle_execute_command(json_data):
    if 'logged_in' not in session:
        return
    command = json_data.get('command')
    if not command:
        return

    emit('response', {'data': f'$ {command}\n'})
    try:
        # 使用 subprocess 执行命令，捕获 stdout 和 stderr
        # 注意：为了安全，不使用 shell=True
        # 安全警告：直接执行来自Web的命令有巨大风险，生产环境需要严格的命令白名单
        process = subprocess.Popen(
            command.split(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace'
        )
        
        # 实时读取输出
        while True:
            output = process.stdout.readline()
            if output == '' and process.poll() is not None:
                break
            if output:
                emit('response', {'data': output})
        
        # 捕获错误输出
        stderr_output = process.stderr.read()
        if stderr_output:
            emit('response', {'data': stderr_output})

    except FileNotFoundError:
        emit('response', {'data': f'Command not found: {command.split()[0]}\n'})
    except Exception as e:
        emit('response', {'data': f'Error executing command: {str(e)}\n'})

# --- Systemd 定时器管理蓝图路由 ---
@systemd_manager_bp.route('/')
@login_required
def systemd_manager_index():
    return render_template('systemd.html')

@systemd_manager_bp.route('/timers')
@login_required
def get_systemd_timers():
    """获取 systemd 定时器列表。"""
    command = SYSTEMCTL_COMMAND + ["list-unit-files", "--type=timer", "--all", "--no-pager"]
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
    
    if result.returncode != 0:
        return jsonify({"status": "error", "message": result.stderr}), 500

    output = result.stdout
    lines = output.strip().split('\n')
    timers = []
    if len(lines) > 1 and "UNIT FILE" in lines[0]: # 检查新的表头
        # 正则表达式用于解析 `list-unit-files` 的输出
        # 示例输出格式: unit_name.timer                    enabled
        pattern = re.compile(r'^\s*(\S+\.timer)\s+(\S+)\s+\S+\s*$')
        for line in lines[1:]:
            if "unit files listed" in line: # 兼容结尾
                break
            match = pattern.match(line)
            if match:
                timers.append({
                    'unit': match.group(1),
                    'state': match.group(2) # enabled, disabled, static等
                })
    return jsonify({"status": "success", "timers": timers})

@systemd_manager_bp.route('/timers/detail')
@login_required
def get_systemd_timer_detail():
    """获取 systemd 定时器的详细信息。"""
    unit = request.args.get('unit')
    if not unit:
        return jsonify({"status": "error", "message": "Unit name is required."}), 400

    command = SYSTEMCTL_COMMAND + ["show", unit, "--no-pager"]
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')

    if result.returncode != 0:
        return jsonify({"status": "error", "message": result.stderr}), 500

    output = result.stdout
    details = {}
    for line in output.strip().split('\n'):
        if '=' in line:
            key, value = line.split('=', 1)
            details[key.strip()] = value.strip()
    
    return jsonify({"status": "success", "detail": details})

@systemd_manager_bp.route('/timers/logs')
@login_required
def get_systemd_timer_logs():
    """获取 systemd 定时器的运行日志。"""
    unit = request.args.get('unit')
    if not unit:
        return jsonify({"status": "error", "message": "Unit name is required."}), 400
    
    # 限制日志输出行数，避免过大响应
    lines = request.args.get('lines', '100') # 默认100行
    try:
        lines = int(lines)
        if lines <= 0:
            lines = 100
    except ValueError:
        lines = 100

    command = ["journalctl", "-u", unit, f"--lines={lines}", "--no-pager"]
    # 对于非root用户，可能需要加上 --user 参数，但是 journalctl 默认会根据用户自动判断
    # 考虑到 systemctl 命令已经处理了用户，这里journalctl应该也可以
    
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')

    if result.returncode != 0:
        return jsonify({"status": "error", "message": result.stderr}), 500
    
    return jsonify({"status": "success", "logs": result.stdout})


@systemd_manager_bp.route('/timers/action', methods=['POST'])
@login_required
def systemd_timer_action():
    """执行 systemd 定时器操作 (start, stop, enable, disable)。"""
    action = request.json.get('action')
    unit = request.json.get('unit')
    if not action or not unit or action not in ['start', 'stop', 'enable', 'disable']:
        return jsonify({"status": "error", "message": "无效的参数。"}), 400
    
    result = run_systemctl_command([action, unit])
    # 对于 enable/disable 操作，即使有警告也认为是成功的
    if result['status'] == 'success' or (action in ['enable', 'disable'] and result['status'] == 'warning'):
        return jsonify({"status": "success", "message": f"定时器 '{unit}' 已成功执行 '{action}' 操作。"}), 200
    else:
        return jsonify({"status": "error", "message": result['message'] or result['stderr']}), 500

@systemd_manager_bp.route('/timers/create', methods=['POST'])
@login_required
def create_systemd_timer():
    """创建新的 systemd 定时器和服务。"""
    data = request.json
    name = data.get('name')
    description = data.get('description')
    command = data.get('command')
    on_calendar = data.get('on_calendar')

    if not all([name, description, command, on_calendar]):
        return jsonify({"status": "error", "message": "所有字段都是必填项。"}), 400
    
    # 安全性：确保名称只包含字母、数字、下划线和短横线
    if not re.match(r'^[a-zA-Z0-9_-]+$', name):
        return jsonify({"status": "error", "message": "名称只能包含字母、数字、下划线和短横线。"}), 400
        
    service_filename = f"{name}.service"
    timer_filename = f"{name}.timer"
    
    service_path = os.path.join(SYSTEMD_PATH, service_filename)
    timer_path = os.path.join(SYSTEMD_PATH, timer_filename)

    if os.path.exists(service_path) or os.path.exists(timer_path):
        return jsonify({"status": "error", "message": "同名服务或定时器已存在。"}), 400

    service_content = f"""
[Unit]
Description={description}

[Service]
Type=oneshot
ExecStart=/bin/bash -c "{command}"

[Install]
WantedBy=multi-user.target
"""

    timer_content = f"""
[Unit]
Description=定时执行: {description}

[Timer]
OnCalendar={on_calendar}
Persistent=true

[Install]
WantedBy=timers.target
"""
    try:
        os.makedirs(SYSTEMD_PATH, exist_ok=True)
        with open(service_path, 'w') as f:
            f.write(service_content.strip())
        with open(timer_path, 'w') as f:
            f.write(timer_content.strip())

        # 重载 systemd daemon
        run_systemctl_command(["daemon-reload"])
        
        return jsonify({"status": "success", "message": f"定时器 '{name}' 已成功创建。"}), 201
    except Exception as e:
        return jsonify({"status": "error", "message": f"创建文件失败: {str(e)}"}), 500

@systemd_manager_bp.route('/timers/delete', methods=['POST'])
@login_required
def delete_systemd_timer():
    """删除 systemd 定时器和服务。"""
    unit = request.json.get('unit')
    if not unit:
        return jsonify({"status": "error", "message": "Unit is required."}), 400

    service_unit = unit.replace('.timer', '.service')
    
    # 停止并禁用定时器
    run_systemctl_command(["stop", unit])
    run_systemctl_command(["disable", unit])
    
    # 删除文件
    try:
        timer_path = os.path.join(SYSTEMD_PATH, unit)
        service_path = os.path.join(SYSTEMD_PATH, service_unit)
        if os.path.exists(timer_path):
            os.remove(timer_path)
        if os.path.exists(service_path):
            os.remove(service_path)
        
        # 重载 systemd daemon
        run_systemctl_command(["daemon-reload"])

        return jsonify({"status": "success", "message": f"定时器 '{unit}' 已被删除。"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": f"删除文件失败: {str(e)}"}), 500

# 注册蓝图
app.register_blueprint(dashboard_bp)
app.register_blueprint(file_manager_bp)
app.register_blueprint(process_manager_bp)
app.register_blueprint(terminal_bp)
app.register_blueprint(systemd_manager_bp)

if __name__ == '__main__':
    # 使用 socketio.run() 启动应用，以支持 WebSocket
    socketio.run(app, host='0.0.0.0', port=5001, debug=True)