import os
import re
import subprocess
from flask import Blueprint, render_template, jsonify, request, current_app
from .utils import login_required, run_systemctl_command

systemd_manager_bp = Blueprint('systemd_manager', __name__, url_prefix='/systemd_manager')

@systemd_manager_bp.route('/')
@login_required
def systemd_manager_index():
    return render_template('systemd.html')

@systemd_manager_bp.route('/timers')
@login_required
def get_systemd_timers():
    """获取 systemd 定时器列表。"""
    command = current_app.config['SYSTEMCTL_COMMAND'] + ["list-unit-files", "--type=timer", "--all", "--no-pager"]
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

    command = current_app.config['SYSTEMCTL_COMMAND'] + ["show", unit, "--no-pager"]
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
    
    service_path = os.path.join(current_app.config['SYSTEMD_PATH'], service_filename)
    timer_path = os.path.join(current_app.config['SYSTEMD_PATH'], timer_filename)

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
        os.makedirs(current_app.config['SYSTEMD_PATH'], exist_ok=True)
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
        timer_path = os.path.join(current_app.config['SYSTEMD_PATH'], unit)
        service_path = os.path.join(current_app.config['SYSTEMD_PATH'], service_unit)
        if os.path.exists(timer_path):
            os.remove(timer_path)
        if os.path.exists(service_path):
            os.remove(service_path)
        
        # 重载 systemd daemon
        run_systemctl_command(["daemon-reload"])

        return jsonify({"status": "success", "message": f"定时器 '{unit}' 已被删除。"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": f"删除文件失败: {str(e)}"}), 500