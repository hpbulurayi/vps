from vps_dashboard import create_app
import os
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
load_dotenv()

app, socketio = create_app(debug=True)

@app.cli.command("list-routes")
def list_routes():
    """List all available routes."""
    import urllib
    output = []
    for rule in app.url_map.iter_rules():
        options = {}
        for arg in rule.arguments:
            options[arg] = f"[{arg}]"
        
        methods = ','.join(rule.methods)
        url = urllib.parse.unquote(rule.endpoint)
        line = f"{url:50s} {methods:20s} {rule.rule}"
        output.append(line)
    
    for line in sorted(output):
        print(line)

if __name__ == '__main__':
    # 启动时打印提示信息
    base_path = app.config.get('BASE_PATH', '').rstrip('/')
    host = '0.0.0.0'
    port = 5001
    print(f" * Flask-SocketIO server running on http://{host}:{port}{base_path}")
    print(f" * Use 'flask list-routes' to see all available routes.")
    socketio.run(app, host=host, port=port)