def init(name):
    print(f"Python-плагин '{name}' инициализирован")

def handle_message(message):
    return f"Здравствуй, {message}!"

def shutdown(name=None):
    print("Плагин hello выгружен")