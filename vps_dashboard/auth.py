from flask import Blueprint, render_template, request, redirect, url_for, session, current_app
from .utils import login_required

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username in current_app.config['USERS'] and current_app.config['USERS'][username] == password:
            session['logged_in'] = True
            return redirect(url_for('dashboard.dashboard_index')) # 登录成功重定向到仪表盘
        else:
            return render_template('login.html', error='Invalid credentials')
    return render_template('login.html')

@auth_bp.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('auth.login'))