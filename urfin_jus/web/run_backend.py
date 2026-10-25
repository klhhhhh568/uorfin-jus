from web_server import app, socketio

if __name__ == '__main__':
    # Это правильный способ запуска для версий python-socketio, которые вы используете.
    socketio.run(app, host='127.0.0.1', port=5000, debug=False)