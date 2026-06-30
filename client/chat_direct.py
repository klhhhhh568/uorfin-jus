import sys, os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'core'))
from openrouter_adapter import OpenRouterAdapter

try:
    adapter = OpenRouterAdapter()
    if not adapter.configured:
        print("Ошибка: OpenRouter не настроен. Проверьте .env")
        exit(1)
except Exception as e:
    print(f"Ошибка инициализации адаптера: {e}")
    exit(1)

print("Чат с Урфином (прямой). Для выхода /exit")
while True:
    try:
        user = input("Вы: ")
        if user.lower() in ("/exit", "/выход"):
            break
        answer = adapter.query(user, temperature=0.7)
        print(f"Урфин: {answer}")
    except KeyboardInterrupt:
        break
    except Exception as e:
        print(f"Ошибка: {e}")