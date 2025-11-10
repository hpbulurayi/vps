from flask import Flask, redirect, url_for, g
from flask_socketio import SocketIO
import os
import json
from .utils import login_required # 导入 login_required

socketio = SocketIO()

def create_app(debug=False):
    """Create an application."""
    app = Flask(__name__, template_folder='templates')
    app.config.from_object('vps_dashboard.config')
    app.debug = debug
    
    # 从配置中获取 BASE_PATH
    base_path = app.config.get('BASE_PATH', '').rstrip('/')

    # 使用上下文处理器将 base_path 注入到模板中
    @app.context_processor
    def inject_base_path():
        return dict(base_path=base_path)

    # 加载用户凭据
    credentials_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'credentials.json')
    try:
        with open(credentials_path, 'r') as f:
            app.config['USERS'] = json.load(f)
    except FileNotFoundError:
        app.config['USERS'] = {} # 如果文件不存在，则设置为空

    # 确保文件管理器根目录存在
    os.makedirs(app.config['FILE_MANAGER_ROOT'], exist_ok=True)

    from .auth import auth_bp
    app.register_blueprint(auth_bp, url_prefix=f'{base_path}')

    from .dashboard import dashboard_bp
    app.register_blueprint(dashboard_bp, url_prefix=f'{base_path}/dashboard')

    from .file_manager import file_manager_bp
    app.register_blueprint(file_manager_bp, url_prefix=f'{base_path}/file_manager')

    from .process_manager import process_manager_bp
    app.register_blueprint(process_manager_bp, url_prefix=f'{base_path}/process_manager')

    from .systemd_manager import systemd_manager_bp
    app.register_blueprint(systemd_manager_bp, url_prefix=f'{base_path}/systemd_manager')

    from .terminal import terminal_bp
    from .pyxterm_terminal import register_socketio_events
    app.register_blueprint(terminal_bp, url_prefix=f'{base_path}/terminal')
    
    # 为 Socket.IO 设置路径
    socketio_path = f'{base_path}/socket.io'
    register_socketio_events(socketio)

    # 主路由重定向
    @app.route(f'{base_path}/')
    @login_required # 添加 login_required 装饰器
    def index():
        return redirect(url_for('dashboard.dashboard_index'))

    socketio.init_app(app, async_mode='eventlet', path=socketio_path)
    return app, socketio