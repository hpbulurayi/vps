import subprocess
import re
from flask import Blueprint, jsonify, request, render_template
from .utils import login_required

screen_manager_bp = Blueprint('screen_manager', __name__, url_prefix='/screen_manager')

@screen_manager_bp.route('/')
@login_required
def screen_manager_index():
    """渲染 Screen 会话管理页面。"""
    return render_template('screen.html')

def _parse_screen_ls_output(output):
    """
    解析 `screen -ls` 的输出，返回一个结构化的会话列表。
    示例输出:
        There are screens on:
                97989.my-session      (Detached)
                97960.pts-0.localhost   (Attached)
        2 Sockets in /run/screen/S-user.
    """
    sessions = []
    # 匹配 "97989.my-session      (Detached)" 这样的行
    pattern = re.compile(r'\t(\d+\.[^\t\s]+)\t+\(([^)]+)\)')
    lines = output.strip().split('\n')
    
    for line in lines:
        match = pattern.match(line)
        if match:
            session_id_full = match.group(1)
            status = match.group(2)
            
            pid, name = session_id_full.split('.', 1)
            
            sessions.append({
                'id': session_id_full,
                'pid': pid,
                'name': name,
                'status': status
            })
    return sessions

@screen_manager_bp.route('/sessions', methods=['GET'])
@login_required
def list_screen_sessions():
    """获取所有 screen 会话的列表。"""
    try:
        # 使用 -wipe 参数可以清理死掉的会话
        result = subprocess.run(['screen', '-ls'], capture_output=True, text=True, check=True)
        sessions = _parse_screen_ls_output(result.stdout)
        return jsonify({"status": "success", "sessions": sessions})
    except FileNotFoundError:
        return jsonify({"status": "error", "message": "screen command not found. Is GNU Screen installed?"}), 500
    except subprocess.CalledProcessError as e:
        # 如果没有活动的 screen 会话，`screen -ls` 可能会返回非零退出码和特定消息
        if "No Sockets found" in e.stdout or "No Sockets found" in e.stderr:
            return jsonify({"status": "success", "sessions": []})
        return jsonify({"status": "error", "message": e.stderr or e.stdout}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@screen_manager_bp.route('/sessions', methods=['POST'])
@login_required
def create_screen_session():
    """创建一个新的 screen 会话。"""
    session_name = request.json.get('session_name')
    if not session_name or not re.match(r'^[a-zA-Z0-9_-]+$', session_name):
        return jsonify({"status": "error", "message": "Invalid session name. Use letters, numbers, underscore, or dash."}), 400

    try:
        # 创建一个分离的、有命名的新会话，并在其中执行 bash
        subprocess.run(['screen', '-S', session_name, '-dm', 'bash'], check=True)
        return jsonify({"status": "success", "message": f"Screen session '{session_name}' created."})
    except FileNotFoundError:
        return jsonify({"status": "error", "message": "screen command not found."}), 500
    except subprocess.CalledProcessError as e:
        return jsonify({"status": "error", "message": e.stderr or e.stdout}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@screen_manager_bp.route('/sessions/<session_id>/kill', methods=['POST'])
@login_required
def kill_screen_session(session_id):
    """终止一个指定的 screen 会话。"""
    if not session_id:
        return jsonify({"status": "error", "message": "Session ID is required."}), 400
    
    try:
        # -S 指定会话ID/名称，-X quit 发送退出命令
        subprocess.run(['screen', '-S', session_id, '-X', 'quit'], check=True)
        return jsonify({"status": "success", "message": f"Screen session '{session_id}' has been killed."})
    except FileNotFoundError:
        return jsonify({"status": "error", "message": "screen command not found."}), 500
    except subprocess.CalledProcessError as e:
        # 如果会话已经不存在，可能会报错，但我们可以将其视为成功
        return jsonify({"status": "success", "message": f"Kill command sent to session '{session_id}'."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500