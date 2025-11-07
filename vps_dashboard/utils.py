import os
import functools
import subprocess
from flask import session, redirect, url_for, jsonify, current_app

def is_admin():
    """检查当前用户是否为管理员 (Linux/macOS 的 root 或 Windows 的管理员)。"""
    try:
        if os.name == 'nt':
            # 在 Windows 上，检查是否具有管理员权限
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        else:
            # 在类 Unix 系统上，检查用户 ID 是否为 0 (root)
            return os.geteuid() == 0
    except Exception:
        return False

def login_required(view):
    """用于保护路由的装饰器，要求用户已登录。"""
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('auth.login'))
        return view(**kwargs)
    return wrapped_view

def _get_safe_path(req_path, base_dir=None, check_exists=False, is_dir=False, check_file=False):
    """
    安全地获取并验证文件路径。
    确保所有操作都在指定的 base_dir 范围内。
    """
    if base_dir is None:
        if is_admin():
            # 对于管理员，允许在真实文件系统根目录下操作
            base_dir = os.path.abspath('/')
        else:
            base_dir = current_app.config['FILE_MANAGER_ROOT']
        
    # 如果 req_path 为空且是管理员，直接使用 base_dir (它已经是正确的根路径)
    if not req_path and is_admin():
        full_path = base_dir
    else:
        full_path = os.path.abspath(os.path.join(base_dir, req_path))

    # 安全检查：对于非管理员，确保请求的路径在 base_dir 目录下
    if not is_admin() and not full_path.startswith(base_dir):
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
    full_command = current_app.config['SYSTEMCTL_COMMAND'] + command_parts
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