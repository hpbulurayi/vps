import subprocess
from flask import Blueprint, render_template, session
from flask_socketio import emit
from .utils import login_required

terminal_bp = Blueprint('terminal', __name__, url_prefix='/terminal')

# 注意：socketio 实例需要在应用工厂中初始化并传递
# 这里我们先定义事件处理器，稍后在 __init__.py 中关联
def register_socketio_events(socketio):
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

@terminal_bp.route('/')
@login_required
def terminal_index():
    return render_template('terminal.html')