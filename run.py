from vps_dashboard import create_app

app, socketio = create_app(debug=True)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5001)