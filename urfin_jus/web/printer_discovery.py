import logging
import socket
from typing import Callable, Dict, Optional, Tuple, List
from zeroconf import Zeroconf, ServiceBrowser, ServiceListener

logger = logging.getLogger(__name__)

# Тип колбэка для обнаружения/удаления принтера
PrinterCallback = Callable[[Dict[str, str]], None]

class PrinterDiscoveryListener(ServiceListener):
    """
    Слушатель Zeroconf для обнаружения 3D-принтеров в локальной сети.
    """

    def __init__(self, on_discovered: PrinterCallback, on_removed: Optional[PrinterCallback] = None):
        """
        :param on_discovered: Функция, вызываемая при обнаружении принтера.
                              Принимает словарь с ключами: name, ip, port, server, properties.
        :param on_removed:    Функция, вызываемая при исчезновении принтера из сети.
                              Принимает тот же словарь, что и on_discovered.
        """
        self.on_discovered = on_discovered
        self.on_removed = on_removed

    def _parse_service_info(self, zc: Zeroconf, type_: str, name: str) -> Optional[Dict[str, str]]:
        """Извлекает данные принтера из информации о сервисе."""
        try:
            info = zc.get_service_info(type_, name)
            if not info or not info.addresses:
                return None

            # Берем первый адрес (предпочитаем IPv4, если есть)
            ip_address = None
            for addr in info.addresses:
                try:
                    ip = socket.inet_ntop(socket.AF_INET, addr)
                    ip_address = ip
                    break  # найден IPv4 – используем его
                except (ValueError, OSError):
                    # возможно, это IPv6, пробуем дальше
                    try:
                        ip = socket.inet_ntop(socket.AF_INET6, addr)
                        ip_address = ip
                        break
                    except (ValueError, OSError):
                        continue

            if not ip_address:
                logger.warning("Обнаружен сервис %s, но не удалось определить IP-адрес", name)
                return None

            # Имя принтера берём как первую часть имени сервиса (до точки)
            friendly_name = name.split('.')[0] if '.' in name else name
            return {
                'name': friendly_name,
                'ip': ip_address,
                'port': str(info.port),
                'server': info.server,
                'properties': {k.decode('utf-8', errors='replace'): v.decode('utf-8', errors='replace')
                               for k, v in info.properties.items()}
            }
        except Exception as e:
            logger.exception("Ошибка при разборе сервиса %s: %s", name, e)
            return None

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Вызывается при обнаружении нового сервиса."""
        printer_data = self._parse_service_info(zc, type_, name)
        if printer_data:
            logger.info("Обнаружен принтер: %s (%s:%s)", printer_data['name'],
                        printer_data['ip'], printer_data['port'])
            self.on_discovered(printer_data)

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Вызывается при удалении сервиса (принтер отключился)."""
        if self.on_removed:
            # Передаём только идентификационную информацию, как минимум имя и IP
            friendly_name = name.split('.')[0] if '.' in name else name
            # Попытаемся получить IP из кеша (уже недоступен, поэтому используем имя)
            data = {'name': friendly_name, 'ip': '', 'port': '', 'server': name, 'properties': {}}
            logger.info("Принтер удалён: %s", friendly_name)
            self.on_removed(data)

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Вызывается при обновлении информации о сервисе."""
        # Можно обработать как обновление, но обычно это не критично.
        pass


class PrinterDiscovery:
    """
    Управляет процессом обнаружения принтеров в локальной сети через Zeroconf.
    """

    def __init__(self):
        self.zeroconf: Optional[Zeroconf] = None
        self.browsers: List[ServiceBrowser] = []

    def start(self, on_discovered: PrinterCallback, on_removed: Optional[PrinterCallback] = None,
              custom_types: Optional[List[str]] = None) -> None:
        """
        Запускает обнаружение принтеров.

        :param on_discovered: Функция, вызываемая при обнаружении принтера.
        :param on_removed:    Функция, вызываемая при исчезновении принтера.
        :param custom_types:  Список дополнительных типов Zeroconf-сервисов для поиска.
                              По умолчанию используются предопределённые типы.
        """
        if self.zeroconf:
            self.stop()

        self.zeroconf = Zeroconf()
        listener = PrinterDiscoveryListener(on_discovered, on_removed)

        # Базовый набор сервисов, характерных для 3D-принтеров
        default_types = [
            "_printer._tcp.local.",
            "_octoprint._tcp.local.",
            "_ultimaker._tcp.local.",
            "_bambu._tcp.local.",
            "_http._tcp.local.",           # для веб-интерфейсов (Creality Wi-Fi и др.)
            "_https._tcp.local.",
            "_prusa-connect._tcp.local.",   # Prusa Connect
            "_creality._tcp.local.",        # Creality Wi-Fi Box
            "_reprap._tcp.local.",          # RepRapFirmware
        ]
        if custom_types:
            service_types = list(set(default_types + custom_types))
        else:
            service_types = default_types

        for service_type in service_types:
            try:
                browser = ServiceBrowser(self.zeroconf, service_type, listener)
                self.browsers.append(browser)
                logger.debug("Запущен ServiceBrowser для %s", service_type)
            except Exception as e:
                logger.error("Не удалось запустить ServiceBrowser для %s: %s", service_type, e)

        logger.info("Обнаружение принтеров запущено с %d типами сервисов", len(self.browsers))

    def stop(self) -> None:
        """Останавливает обнаружение и освобождает ресурсы."""
        if self.zeroconf:
            for browser in self.browsers:
                try:
                    browser.cancel()
                except Exception:
                    pass
            self.browsers.clear()
            try:
                self.zeroconf.close()
            except Exception:
                pass
            self.zeroconf = None
            logger.info("Обнаружение принтеров остановлено.")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False


# Функция для удобного одноразового обнаружения
def discover_printers(on_discovered: PrinterCallback, on_removed: Optional[PrinterCallback] = None,
                      duration: Optional[float] = None) -> PrinterDiscovery:
    """
    Запускает обнаружение принтеров. Возвращает объект PrinterDiscovery,
    который можно использовать для остановки обнаружения.

    Пример:
        def handle_printer(printer):
            print(f"Найден принтер: {printer['name']} ({printer['ip']}:{printer['port']})")

        discovery = discover_printers(handle_printer)
        # ... через некоторое время
        discovery.stop()

    :param on_discovered: Функция-обработчик обнаруженных принтеров.
    :param on_removed:    Функция-обработчик удалённых принтеров.
    :param duration:      Если указано (в секундах), обнаружение будет автоматически остановлено
                          через указанное время.
    :return:              Экземпляр PrinterDiscovery для контроля.
    """
    discovery = PrinterDiscovery()
    discovery.start(on_discovered, on_removed)

    if duration is not None:
        import threading
        def auto_stop():
            import time
            time.sleep(duration)
            discovery.stop()
        threading.Thread(target=auto_stop, daemon=True).start()
        logger.info("Обнаружение будет остановлено через %.1f сек.", duration)

    return discovery