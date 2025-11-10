from flask import Blueprint, render_template
from .utils import login_required

terminal_bp = Blueprint('terminal', __name__, url_prefix='/terminal')

@terminal_bp.route('/')
@login_required
def terminal_index():
    """渲染 Web 终端页面。"""
    return render_template('terminal.html')