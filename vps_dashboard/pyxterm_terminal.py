import os
import subprocess
import select
import shlex
import logging
from flask import session, request
from flask_socketio import emit

# 平台特定的导入
if os.name != 'nt':
    import pty
    import termios
    import struct
    import fcntl

# 全局字典，用于存储每个会话的终端进程信息
# 键是 session ID，值是包含 'fd' 和 'child_pid' 的字典
user_sessions = {}

def register_socketio_events(socketio):
    """注册与终端相关的 Socket.IO 事件。"""

    def set_winsize(sid, row, col, xpix=0, ypix=0):
        if os.name != 'nt':
            if sid in user_sessions:
                fd = user_sessions[sid]['fd']
                logging.debug(f"Resizing window for session {sid} to {row}x{col}")
                winsize = struct.pack("HHHH", row, col, xpix, ypix)
                fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)

    def read_and_forward_pty_output(sid):
        max_read_bytes = 1024 * 20
        while sid in user_sessions:
            socketio.sleep(0.01)
            fd = user_sessions.get(sid, {}).get('fd')
            if fd:
                timeout_sec = 0
                (data_ready, _, _) = select.select([fd], [], [], timeout_sec)
                if data_ready:
                    try:
                        output = os.read(fd, max_read_bytes).decode(errors="ignore")
                        socketio.emit("pty-output", {"output": output}, namespace="/pty", to=sid)
                    except OSError:
                        # 当进程结束时，os.read 可能会抛出 OSError
                        logging.info(f"PTY for session {sid} has been closed.")
                        break

    @socketio.on("pty-input", namespace="/pty")
    def pty_input(data):
        """将浏览器输入写入子 PTY。"""
        sid = request.sid
        if sid in user_sessions:
            fd = user_sessions[sid]['fd']
            logging.debug(f"Received input from browser for session {sid}: {data['input']}")
            if fd:
                os.write(fd, data["input"].encode())

    @socketio.on("resize", namespace="/pty")
    def resize(data):
        """调整 PTY 窗口大小。"""
        sid = request.sid
        if sid in user_sessions:
            set_winsize(sid, data['rows'], data['cols'])

    @socketio.on("connect", namespace="/pty")
    def connect():
        """新的客户端连接。"""
        sid = request.sid
        if 'logged_in' not in session:
            logging.warning(f"Unauthorized terminal connection attempt from SID {sid}.")
            return False  # 拒绝未认证的连接

        logging.info(f"New client connected: {sid}")

        if sid in user_sessions:
            logging.info(f"Session {sid} already has a child process.")
            return

        if os.name != 'nt':
            # 为非 Windows 系统创建 PTY 进程
            cmd = ["bash"]  # 或者从配置中读取
            (child_pid, fd) = pty.fork()

            if child_pid == 0:
                # 这是子进程
                subprocess.run(cmd)
                os._exit(0) # 确保子进程在完成后退出
            else:
                # 这是父进程
                user_sessions[sid] = {'fd': fd, 'child_pid': child_pid}
                set_winsize(sid, 50, 50)
                logging.info(f"Started PTY for session {sid} with PID {child_pid}")
                socketio.start_background_task(target=read_and_forward_pty_output, sid=sid)
        else:
            # Windows 兼容性说明
            logging.warning("PTY is not supported on Windows. Interactive terminal will not be available.")
            emit('pty-output', {'output': 'Warning: Full interactive terminal is not supported on Windows.\r\n'}, to=sid)
            # 在这里可以添加一个基于 subprocess 的、功能有限的后备方案
            
    @socketio.on("disconnect", namespace="/pty")
    def disconnect():
        """客户端断开连接。"""
        sid = request.sid
        if sid in user_sessions:
            logging.info(f"Client disconnected: {sid}. Cleaning up session.")
            fd = user_sessions[sid]['fd']
            child_pid = user_sessions[sid]['child_pid']
            
            # 关闭文件描述符和终止子进程
            if fd:
                os.close(fd)
            if child_pid:
                try:
                    os.kill(child_pid, 9) # 强制终止
                except ProcessLookupError:
                    pass # 进程可能已经自己退出了
            
            del user_sessions[sid]