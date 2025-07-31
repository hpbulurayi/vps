from flask import Flask, redirect, url_for
from flask_socketio import SocketIO
import os
from .utils import login_required # 导入 login_required

socketio = SocketIO()

def create_app(debug=False):
    """Create an application."""
    app = Flask(__name__, template_folder='templates')
    app.config.from_object('vps_dashboard.config')
    app.debug = debug

    # 确保文件管理器根目录存在
    os.makedirs(app.config['FILE_MANAGER_ROOT'], exist_ok=True)

    from .auth import auth_bp
    app.register_blueprint(auth_bp)

    from .dashboard import dashboard_bp
    app.register_blueprint(dashboard_bp)

    from .file_manager import file_manager_bp
    app.register_blueprint(file_manager_bp)

    from .process_manager import process_manager_bp
    app.register_blueprint(process_manager_bp)

    from .systemd_manager import systemd_manager_bp
    app.register_blueprint(systemd_manager_bp)

    from .terminal import terminal_bp, register_socketio_events
    app.register_blueprint(terminal_bp)
    register_socketio_events(socketio)

    # 主路由重定向
    @app.route('/')
    @login_required # 添加 login_required 装饰器
    def index():
        return redirect(url_for('dashboard.dashboard_index'))

    socketio.init_app(app, async_mode='eventlet')
    return app, socketio