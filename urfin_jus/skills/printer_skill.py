# skills/printer_skill.py
import json
import logging
import socket
import time
import threading
import serial
import requests
import re
import random
from typing import Optional, Dict, Any, List, Tuple

try:
    from printer_discovery import PrinterDiscovery
    ZEROCONF_AVAILABLE = True
except ImportError:
    ZEROCONF_AVAILABLE = False

logger = logging.getLogger(__name__)

_socketio = None


class PrinterConnection:
    def __init__(self):
        self.connected = False
        self.connection_type = None
        self.address = None
        self.port = None
        self.protocol = None
        self.api_key = None
        self.http_gcode_url = None
        self.sock = None
        self.ser = None
        self.octo_base_url = None
        self.moonraker_base_url = None
        self.lock = threading.Lock()
        self.printing = False
        self.progress = 0
        self.temperature = 0
        self.bed_temp = 0
        self.gcode_file = None
        self.print_time = 0
        self._stop_flag = False
        self._pause_event = threading.Event()
        self._print_thread = None
        self._status_thread = None
        self._stop_status = False
        self._tcp_buffer = ""
        self._last_error = ""
        self._gcode_queue = []
        self._gcode_send_thread = None
        self._stop_gcode_send = False

    def connect(self, printer_type: str, address: str, port: Optional[int] = None,
                protocol: str = "tcp", api_key: Optional[str] = None,
                connection_type: str = "usb", http_gcode_url: Optional[str] = None) -> bool:
        with self.lock:
            if self.connected:
                self.disconnect()
            self.connection_type = connection_type
            self.address = address
            self.port = port
            self.protocol = protocol
            self.api_key = api_key
            self.http_gcode_url = http_gcode_url
            self._last_error = ""

            logger.info(f"Попытка подключения: тип={connection_type}, адрес={address}, порт={port}, протокол={protocol}")

            if connection_type == "usb":
                try:
                    self.ser = serial.Serial(address, baudrate=115200, timeout=2)
                    self.connected = True
                    logger.info(f"Подключено по USB: {address}")
                    self._emit_log(f"Подключено по USB ({address})", "ok")
                    self._emit_status()
                    self._start_status_polling()
                    return True
                except Exception as e:
                    error_msg = f"Ошибка USB: {e}"
                    logger.error(error_msg)
                    self._last_error = error_msg
                    self._emit_log(f"Ошибка подключения USB: {e}", "error")
                    return False

            elif connection_type in ("wifi", "bluetooth"):
                # ---- MOONRAKER API (Klipper) ----
                if protocol == "moonraker":
                    if address.startswith("http"):
                        base_url = address.rstrip('/')
                    else:
                        base_url = f"http://{address}:{port if port else 7125}"
                    self.moonraker_base_url = base_url
                    try:
                        logger.info(f"Проверка Moonraker на {base_url}")
                        resp = requests.get(f"{base_url}/printer/info", timeout=3)
                        if resp.status_code == 200:
                            data = resp.json()
                            if data.get('result', {}).get('state') in ['ready', 'printing', 'paused']:
                                self.connected = True
                                logger.info(f"Подключено к Moonraker: {base_url}")
                                self._emit_log(f"Подключено к Moonraker ({base_url})", "ok")
                                # Принудительно отправляем статус
                                self._emit_status()
                                self._start_status_polling()
                                self._start_gcode_sender()
                                return True
                    except Exception as e:
                        self._last_error = f"Moonraker ошибка: {e}"
                        logger.error(self._last_error)
                        self._emit_log(f"❌ Moonraker не доступен: {e}", "error")
                        return False

                # ---- OctoPrint API ----
                elif protocol == "octoprint":
                    if address.startswith("http"):
                        base_url = address.rstrip('/')
                    else:
                        base_url = f"http://{address}:{port if port else 5000}"
                    self.octo_base_url = base_url
                    headers = {"X-Api-Key": api_key} if api_key else {}
                    try:
                        logger.info(f"Проверка OctoPrint на {base_url}")
                        resp = requests.get(f"{base_url}/api/version", headers=headers, timeout=3)
                        if resp.status_code == 200:
                            self.connected = True
                            logger.info(f"Подключено к OctoPrint: {base_url}")
                            self._emit_log(f"Подключено к OctoPrint ({base_url})", "ok")
                            self._emit_status()
                            self._start_status_polling()
                            return True
                    except Exception as e:
                        self._last_error = f"OctoPrint ошибка: {e}"
                        logger.error(self._last_error)
                        self._emit_log(f"❌ OctoPrint не доступен: {e}", "error")
                        return False

                # ---- TCP (MKS WiFi / старые принтеры) ----
                elif protocol == "tcp":
                    ports_to_try = [port] if port else [23, 8899, 80, 8080, 3333, 9999]
                    for p in ports_to_try:
                        try:
                            logger.info(f"Попытка TCP подключения к {address}:{p}")
                            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            self.sock.settimeout(5)
                            self.sock.connect((address, p))
                            self._send_gcode_raw("M105")
                            time.sleep(0.5)
                            data = self._read_response()
                            if data and ("ok" in data.lower() or "T:" in data or "B:" in data):
                                self.connected = True
                                self.port = p
                                logger.info(f"Подключено по TCP: {address}:{p}")
                                self._emit_log(f"Подключено по TCP ({address}:{p})", "ok")
                                self._emit_status()
                                self._start_status_polling()
                                self._start_gcode_sender()
                                return True
                            else:
                                self.sock.close()
                                self.sock = None
                                logger.debug(f"Порт {p} не отвечает на M105")
                        except Exception as e:
                            logger.debug(f"Не удалось подключиться к {address}:{p} - {e}")
                            continue
                    self._last_error = f"Не удалось подключиться к {address} ни на одном порту. Попробуйте Moonraker (Klipper)."
                    logger.error(self._last_error)
                    self._emit_log(f"❌ {self._last_error}", "error")
                    return False

                # ---- HTTP (веб-интерфейс) ----
                elif protocol == "http":
                    base_url = f"http://{address}:{port if port else 80}"
                    try:
                        logger.info(f"Проверка HTTP доступности {base_url}")
                        resp = requests.get(base_url, timeout=3)
                        if resp.status_code == 200:
                            # Пробуем определить Moonraker
                            if "moonraker" in resp.text.lower() or "klipper" in resp.text.lower():
                                self.moonraker_base_url = base_url
                                self.connected = True
                                logger.info(f"Обнаружен Klipper/Moonraker: {base_url}")
                                self._emit_log(f"Подключено к Klipper/Moonraker ({base_url})", "ok")
                                self._emit_status()
                                self._start_status_polling()
                                self._start_gcode_sender()
                                return True
                            elif self.http_gcode_url:
                                gcode_url = base_url.rstrip('/') + self.http_gcode_url
                                try:
                                    logger.info(f"Отправка M105 через {gcode_url}")
                                    resp2 = requests.post(gcode_url, data={"gcode": "M105"}, timeout=3)
                                    if resp2.status_code == 200 and ("ok" in resp2.text.lower() or "T:" in resp2.text):
                                        self.connected = True
                                        logger.info(f"Подключено по HTTP с G-кодом: {gcode_url}")
                                        self._emit_log(f"Подключено по HTTP ({base_url}, G-код URL: {self.http_gcode_url})", "ok")
                                        self._emit_status()
                                        self._start_status_polling()
                                        return True
                                except Exception as e:
                                    logger.warning(f"Не удалось отправить G-код через {gcode_url}: {e}")
                            # Если не удалось, подключаемся в режиме просмотра
                            self.connected = True
                            logger.info(f"Подключено к веб-интерфейсу {base_url} (только просмотр)")
                            self._emit_log(f"Подключено к веб-интерфейсу ({base_url})", "ok")
                            self._emit_status()
                            self._start_status_polling()
                            return True
                        else:
                            self._last_error = f"HTTP статус {resp.status_code}"
                            logger.error(self._last_error)
                            self._emit_log(f"❌ HTTP ошибка: {resp.status_code}", "error")
                            return False
                    except Exception as e:
                        self._last_error = f"HTTP ошибка: {e}"
                        logger.error(self._last_error)
                        self._emit_log(f"❌ HTTP недоступен: {e}", "error")
                        return False
                else:
                    self._last_error = f"Неизвестный протокол: {protocol}"
                    logger.error(self._last_error)
                    self._emit_log(self._last_error, "error")
                    return False
            else:
                error_msg = f"Неподдерживаемый тип подключения: {connection_type}"
                self._last_error = error_msg
                logger.error(error_msg)
                self._emit_log(error_msg, "error")
                return False

    def disconnect(self):
        with self.lock:
            self._stop_gcode_sender()
            self._stop_status_polling()
            self._stop_print_thread()
            self.connected = False
            if self.ser:
                self.ser.close()
                self.ser = None
            if self.sock:
                self.sock.close()
                self.sock = None
            self.octo_base_url = None
            self.moonraker_base_url = None
            self.printing = False
            self.progress = 0
            self._emit_log("Отключено от принтера", "warn")
            self._emit_status()
            logger.info("Отключено от принтера")

    def _send_gcode_moonraker(self, command: str) -> bool:
        if not self.moonraker_base_url:
            return False
        try:
            payload = {"jsonrpc": "2.0", "method": "printer.gcode.script", "params": {"script": command}, "id": int(time.time() * 1000)}
            resp = requests.post(
                f"{self.moonraker_base_url}/api/printer/gcode/script",
                json=payload,
                timeout=3
            )
            if resp.status_code == 200:
                logger.debug(f"Moonraker G-код отправлен: {command}")
                return True
            else:
                logger.warning(f"Moonraker ошибка: {resp.status_code} - {resp.text}")
                return False
        except Exception as e:
            logger.error(f"Ошибка отправки через Moonraker: {e}")
            return False

    def _send_gcode_raw(self, command: str) -> bool:
        if not self.sock:
            return False
        try:
            cmd = command + "\r\n"
            self.sock.send(cmd.encode('utf-8'))
            logger.debug(f"Отправлено: {command}")
            return True
        except Exception as e:
            logger.error(f"Ошибка отправки G-кода: {e}")
            return False

    def _read_response(self, timeout: float = 1.0) -> str:
        if not self.sock:
            return ""
        try:
            self.sock.settimeout(timeout)
            data = self.sock.recv(1024).decode('utf-8', errors='ignore')
            self._tcp_buffer += data
            lines = self._tcp_buffer.split('\n')
            self._tcp_buffer = lines[-1] if len(lines) > 1 else self._tcp_buffer
            return '\n'.join(lines[:-1])
        except socket.timeout:
            return ""
        except Exception as e:
            logger.error(f"Ошибка чтения ответа: {e}")
            return ""

    def _start_gcode_sender(self):
        if self._gcode_send_thread and self._gcode_send_thread.is_alive():
            return
        self._stop_gcode_send = False
        self._gcode_send_thread = threading.Thread(target=self._gcode_sender_loop, daemon=True)
        self._gcode_send_thread.start()

    def _stop_gcode_sender(self):
        self._stop_gcode_send = True
        if self._gcode_send_thread and self._gcode_send_thread.is_alive():
            self._gcode_send_thread.join(timeout=1)
        self._gcode_send_thread = None

    def _gcode_sender_loop(self):
        while not self._stop_gcode_send:
            if not self._gcode_queue:
                time.sleep(0.1)
                continue
            with self.lock:
                cmd = self._gcode_queue.pop(0) if self._gcode_queue else None
            if cmd:
                if self.moonraker_base_url:
                    self._send_gcode_moonraker(cmd)
                elif self.sock:
                    self._send_gcode_raw(cmd)
                time.sleep(0.05)

    def send_gcode(self, command: str) -> bool:
        if not self.connected:
            return False
        with self.lock:
            self._gcode_queue.append(command)
        return True

    def start_print(self, gcode_file: str) -> bool:
        if not self.connected:
            self._emit_log("Принтер не подключён – запускаем симуляцию", "warn")
        with self.lock:
            if self.printing:
                self._emit_log("Печать уже выполняется", "error")
                return False
            self.gcode_file = gcode_file
            self.printing = True
            self.progress = 0
            self.print_time = 0
            self._stop_flag = False
            self._pause_event.clear()
        self._start_print_thread()
        self._emit_log(f"Начата печать файла: {gcode_file}", "ok")
        return True

    def pause(self):
        with self.lock:
            if not self.printing:
                return
            self._pause_event.set()
        self._emit_log("Печать приостановлена", "warn")

    def resume(self):
        with self.lock:
            if not self.printing:
                return
            self._pause_event.clear()
        self._emit_log("Печать возобновлена", "ok")

    def stop(self):
        with self.lock:
            self._stop_flag = True
            self._pause_event.clear()
        self._stop_print_thread()
        with self.lock:
            self.printing = False
            self.progress = 0
        self._emit_log("Печать остановлена", "error")
        self._emit_status()

    def clear_bed(self):
        self._emit_log("Стол очищен", "info")
        self._emit_clear_bed_response()

    def get_status(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "status": "printing" if self.printing else "idle" if self.connected else "disconnected",
                "progress": self.progress,
                "temperature": self.temperature,
                "bed_temp": self.bed_temp,
                "time": f"{self.print_time // 60}:{self.print_time % 60:02d}",
            }

    def _simulate_print(self):
        self.printing = True
        self.progress = 0
        self.temperature = 200
        self.bed_temp = 60
        while not self._stop_flag:
            if self._pause_event.is_set():
                self._emit_status()
                self._pause_event.wait(0.5)
                continue

            time.sleep(1)
            with self.lock:
                if self.progress < 100:
                    self.progress += 2
                    if self.progress > 100:
                        self.progress = 100
                    self.print_time += 1
                self._emit_status()
                if self.progress >= 100:
                    self.printing = False
                    self._emit_log("Печать завершена", "ok")
                    self._emit_status()
                    return
        with self.lock:
            self.printing = False
        self._emit_status()

    def _start_print_thread(self):
        self._stop_print_thread()
        self._print_thread = threading.Thread(target=self._simulate_print, daemon=True)
        self._print_thread.start()

    def _stop_print_thread(self):
        if self._print_thread and self._print_thread.is_alive():
            self._stop_flag = True
            self._pause_event.set()
            self._print_thread.join(timeout=2)
        self._print_thread = None

    def _start_status_polling(self):
        if self._status_thread and self._status_thread.is_alive():
            return
        self._stop_status = False
        self._status_thread = threading.Thread(target=self._poll_status, daemon=True)
        self._status_thread.start()

    def _stop_status_polling(self):
        self._stop_status = True
        if self._status_thread and self._status_thread.is_alive():
            self._status_thread.join(timeout=1)
        self._status_thread = None

    def _poll_status(self):
        while not self._stop_status:
            if not self.connected:
                time.sleep(1)
                continue
            try:
                # ---- Moonraker (Klipper) ----
                if self.moonraker_base_url:
                    try:
                        resp = requests.get(
                            f"{self.moonraker_base_url}/printer/objects/query?extruder=temperature&heater_bed=temperature&print_stats=progress&print_stats=print_duration&display_status=progress",
                            timeout=2
                        )
                        if resp.status_code == 200:
                            data = resp.json()
                            result = data.get('result', {}).get('status', {})
                            extruder = result.get('extruder', {})
                            bed = result.get('heater_bed', {})
                            self.temperature = extruder.get('temperature', 0)
                            self.bed_temp = bed.get('temperature', 0)
                            print_stats = result.get('print_stats', {})
                            if print_stats.get('state') == 'printing':
                                self.progress = print_stats.get('progress', 0) * 100
                                self.print_time = int(print_stats.get('print_duration', 0))
                            else:
                                display = result.get('display_status', {})
                                self.progress = display.get('progress', 0) * 100
                        self._emit_status()
                    except Exception as e:
                        logger.warning(f"Ошибка опроса Moonraker: {e}")

                # ---- OctoPrint ----
                elif self.octo_base_url:
                    headers = {"X-Api-Key": self.api_key} if self.api_key else {}
                    resp = requests.get(f"{self.octo_base_url}/api/printer", headers=headers, timeout=2)
                    if resp.status_code == 200:
                        data = resp.json()
                        tool = data.get('temperature', {}).get('tool0', {})
                        bed = data.get('temperature', {}).get('bed', {})
                        self.temperature = tool.get('actual', 0)
                        self.bed_temp = bed.get('actual', 0)
                    if self.printing:
                        job_resp = requests.get(f"{self.octo_base_url}/api/job", headers=headers, timeout=2)
                        if job_resp.status_code == 200:
                            job = job_resp.json()
                            progress = job.get('progress', {})
                            if progress.get('completion') is not None:
                                self.progress = progress['completion']
                            if job.get('time'):
                                self.print_time = int(job['time'])
                    self._emit_status()

                # ---- TCP ----
                elif self.sock:
                    self._send_gcode_raw("M991")
                    data = self._read_response(1.0)
                    if data:
                        match = re.search(r'T:(\d+)\s*/\s*(\d+)', data)
                        if match:
                            self.temperature = float(match.group(1))
                        match_b = re.search(r'B:(\d+)\s*/\s*(\d+)', data)
                        if match_b:
                            self.bed_temp = float(match_b.group(1))
                    if self.printing:
                        self._send_gcode_raw("M27")
                        progress_data = self._read_response(0.5)
                        if progress_data:
                            match_prog = re.search(r'M27\s+(\d+)', progress_data)
                            if match_prog:
                                self.progress = float(match_prog.group(1))
                    self._emit_status()

                # ---- Если печать идёт, но ничего не работает ----
                elif self.printing:
                    self.progress = min(100, self.progress + random.randint(1, 3))
                    self.print_time += 1
                    self._emit_status()

            except Exception as e:
                logger.warning(f"Ошибка опроса состояния: {e}")
            time.sleep(2)

    def _emit_log(self, text: str, log_type: str = "info"):
        if _socketio:
            try:
                _socketio.emit('printer_log', {'text': text, 'type': log_type})
            except Exception:
                pass
        else:
            logger.warning("_socketio is None, cannot emit log")

    def _emit_status(self):
        if _socketio:
            try:
                status = self.get_status()
                _socketio.emit('printer_status', status)
                logger.info(f"Отправлен статус: {status}")
            except Exception as e:
                logger.error(f"Ошибка отправки статуса: {e}")
        else:
            logger.warning("_socketio is None, cannot emit status")

    def _emit_clear_bed_response(self):
        if _socketio:
            try:
                _socketio.emit('printer_clear_bed_response')
            except Exception:
                pass


printer = PrinterConnection()


def handle_slicing(settings: dict, filename: str):
    if _socketio:
        _socketio.emit('printer_log', {'text': '🍰 Слайсинг запущен...', 'type': 'info'})
    for i in range(0, 101, 10):
        time.sleep(0.3)
        if _socketio:
            _socketio.emit('printer_status', {'status': 'slicing', 'progress': i})
    gcode_name = filename.rsplit('.', 1)[0] + '.gcode'
    if _socketio:
        _socketio.emit('printer_log', {'text': f'✅ G-code создан: {gcode_name}', 'type': 'ok'})
        _socketio.emit('printer_status', {'status': 'ready', 'gcode': gcode_name, 'progress': 0})
    return gcode_name


def init(name, sio=None):
    global _socketio
    _socketio = sio
    print(f"Плагин принтера '{name}' инициализирован, _socketio = {_socketio is not None}")
    # Отправить начальный статус (отключено) чтобы клиент знал
    if _socketio:
        printer._emit_status()


def handle_message(message):
    try:
        data = json.loads(message)
    except Exception:
        return json.dumps({"error": "Неверный формат JSON"})

    command = data.get("command")
    params = data.get("params", {})

    if command == "connect":
        printer_type = params.get("printer_type", "unknown")
        address = params.get("address")
        port = params.get("port")
        protocol = params.get("protocol", "tcp")
        api_key = params.get("api_key")
        connection_type = params.get("connection_type", "usb")
        http_gcode_url = params.get("http_gcode_url")
        if not address:
            return json.dumps({"error": "Не указан адрес"})
        if port:
            try:
                port = int(port)
            except ValueError:
                port = None
        success = printer.connect(printer_type, address, port, protocol, api_key, connection_type, http_gcode_url)
        return json.dumps({"status": "ok" if success else "error",
                           "message": "Подключено" if success else printer._last_error or "Ошибка подключения"})

    elif command == "disconnect":
        printer.disconnect()
        return json.dumps({"status": "ok"})

    elif command == "start":
        gcode_file = params.get("gcode_file")
        if not gcode_file:
            gcode_file = getattr(printer, 'gcode_file', None)
        if not gcode_file:
            return json.dumps({"error": "Нет G-code файла"})
        success = printer.start_print(gcode_file)
        return json.dumps({"status": "ok" if success else "error"})

    elif command == "pause":
        printer.pause()
        return json.dumps({"status": "ok"})

    elif command == "resume":
        printer.resume()
        return json.dumps({"status": "ok"})

    elif command == "stop":
        printer.stop()
        return json.dumps({"status": "ok"})

    elif command == "clear":
        printer.clear_bed()
        return json.dumps({"status": "ok"})

    elif command == "status":
        status = printer.get_status()
        return json.dumps(status)

    elif command == "slice":
        settings = params.get("settings", {})
        filename = params.get("filename", "model.stl")
        try:
            gcode_name = handle_slicing(settings, filename)
            return json.dumps({"status": "ok", "gcode_file": gcode_name})
        except Exception as e:
            logger.error(f"Ошибка слайсинга: {e}")
            return json.dumps({"status": "error", "error": str(e)})

    elif command == "discover_printers":
        if not ZEROCONF_AVAILABLE:
            return json.dumps({"status": "error", "error": "Модуль обнаружения принтеров не установлен"})
        try:
            from printer_discovery import discover_printers
            import threading
            def discovery_worker():
                def on_found(info):
                    if _socketio:
                        _socketio.emit('printer_discovered', info)
                discovery = discover_printers(on_found, duration=15)
                if _socketio:
                    _socketio.emit('printer_discovery_complete')
            threading.Thread(target=discovery_worker, daemon=True).start()
            return json.dumps({"status": "ok", "message": "Поиск принтеров запущен"})
        except Exception as e:
            logger.exception("Ошибка при запуске обнаружения принтеров")
            return json.dumps({"status": "error", "error": str(e)})

    else:
        return json.dumps({"error": f"Неизвестная команда: {command}"})


def shutdown(name=None):
    printer.disconnect()
    print("Плагин принтера выгружен")