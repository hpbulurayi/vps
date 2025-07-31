import os
import getpass

SECRET_KEY = 'your_super_secret_key_here'

# 认证凭据 (生产环境请勿硬编码，应从安全配置加载)
USERS = {
    "admin": "password123" 
}

# 可通过环境变量设置文件管理器的根目录，默认为当前脚本目录下的 'managed_files'
FILE_MANAGER_ROOT = os.getenv('FILE_MANAGER_ROOT', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'managed_files'))

# --- 动态配置 systemd 路径和命令 ---
CURRENT_USER = getpass.getuser()
if CURRENT_USER == 'root':
    SYSTEMD_PATH = '/etc/systemd/system'
    SYSTEMCTL_COMMAND = ['systemctl']
else:
    SYSTEMD_PATH = os.path.expanduser('~/.config/systemd/user')
    SYSTEMCTL_COMMAND = ['systemctl', '--user']