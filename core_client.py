import socket
import json
import logging
import time

logging.basicConfig(filename='/tmp/core_client.log', level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s')

def send_to_core(msg_dict, max_retries=3, delay=0.5):
    for attempt in range(max_retries):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(60.0)  # таймаут на подключение и отправку
                s.connect(("127.0.0.1", 5555))
                s.sendall(json.dumps(msg_dict, ensure_ascii=False).encode('utf-8'))

                # Отключаем таймаут, чтобы спокойно прочитать ответ до закрытия
                s.settimeout(None)
                chunks = []
                while True:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    chunks.append(chunk)
                data = b''.join(chunks)
                if not data:
                    raise ConnectionError("пустой ответ")

                raw = data.decode('utf-8')
                logging.debug(f"Получено {len(raw)} байт от ядра")
                return json.loads(raw)

        except (ConnectionRefusedError, socket.timeout) as e:
            logging.warning(f"Попытка {attempt+1}: {e}")
            if attempt == max_retries - 1:
                logging.error(f"Ядро недоступно: {e}")
                return {"text": "Ошибка: ядро Урфина не отвечает"}
            time.sleep(delay)
        except json.JSONDecodeError as e:
            logging.error(f"Ошибка парсинга JSON: {e}\nСырой ответ: {raw[:500]}")
            return {"text": "Ошибка: неверный ответ от ядра"}
        except Exception as e:
            logging.exception("Неожиданная ошибка")
            return {"text": f"Ошибка связи: {e}"}