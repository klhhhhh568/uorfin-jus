import socket, json

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.connect(("127.0.0.1", 5555))
    s.sendall(b'ping')
    data = json.loads(s.recv(1024).decode())
    print(data['text'])