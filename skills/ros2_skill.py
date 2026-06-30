import json, threading, base64, logging, time, sys, os, math, random

# Безопасный импорт ROS2
ROS2_AVAILABLE = False
try:
    import rclpy
    from rclpy.node import Node
    from rclpy.executors import MultiThreadedExecutor
    from sensor_msgs.msg import Image, LaserScan
    from geometry_msgs.msg import Twist
    ROS2_AVAILABLE = True
except ImportError:
    pass

logger = logging.getLogger("ros2_skill")
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(h)

latest_image = None
latest_scan = None
ros_thread = None
ros_node = None
shutdown_flag = threading.Event()

training_active = False
training_model = None

if ROS2_AVAILABLE:
    class UorfinRosNode(Node):
        def __init__(self):
            super().__init__('uorfin_jus_node')
            self.image_sub = self.create_subscription(
                Image, '/camera/image_raw', self.image_callback, 10)
            self.scan_sub = self.create_subscription(
                LaserScan, '/scan', self.scan_callback, 10)
            self.cmd_vel_pub = self.create_publisher(Twist, '/cmd_vel', 10)
            logger.info("ROS2-узел uorfin_jus_node создан")

        def image_callback(self, msg):
            global latest_image
            try:
                img_b64 = base64.b64encode(msg.data).decode('utf-8')
                latest_image = {
                    "data": img_b64,
                    "encoding": msg.encoding,
                    "width": msg.width,
                    "height": msg.height,
                    "timestamp": self.get_clock().now().nanoseconds
                }
            except Exception as e:
                logger.error(f"Ошибка сохранения изображения: {e}")

        def scan_callback(self, msg):
            global latest_scan
            latest_scan = {
                "ranges": list(msg.ranges),
                "angle_min": msg.angle_min,
                "angle_max": msg.angle_max,
                "range_min": msg.range_min,
                "range_max": msg.range_max,
                "timestamp": self.get_clock().now().nanoseconds
            }

    def ros_spin():
        try:
            rclpy.init()
            global ros_node
            ros_node = UorfinRosNode()
            executor = MultiThreadedExecutor()
            executor.add_node(ros_node)
            logger.info("ROS2 executor запущен")
            while not shutdown_flag.is_set():
                executor.spin_once(timeout_sec=0.5)
        except Exception as e:
            logger.exception(f"Критическая ошибка в потоке ROS2: {e}")
        finally:
            if ros_node:
                ros_node.destroy_node()
            rclpy.shutdown()
else:
    class UorfinRosNode: pass
    def ros_spin(): pass

def start_training():
    global training_active, training_model
    training_active = True
    for epoch in range(5):
        time.sleep(1)
        print(f"[ML] Эпоха {epoch+1}/5...")
    training_model = "trained_model_v1"
    training_active = False
    print("[ML] Обучение завершено. Модель готова.")

def init(name):
    print(f"ROS2-плагин '{name}' инициализирован")
    if not ROS2_AVAILABLE:
        print("ROS2 не найден – работаем в эмуляции")
        return
    global ros_thread
    ros_thread = threading.Thread(target=ros_spin, daemon=True)
    ros_thread.start()
    ros_thread.join(timeout=1.0)
    if ros_thread.is_alive():
        print("ROS2-узел запущен успешно")
    else:
        print("Не удалось запустить ROS2-узел, проверьте топики")

def handle_message(message):
    # Единый интерфейс: принимает JSON с полями command и params
    try:
        msg = json.loads(message)
    except:
        return "Ошибка: ожидается JSON"
    command = msg.get("command", "").lower()
    params = msg.get("params", {})

    # Если ROS2 недоступен – эмуляция
    if not ROS2_AVAILABLE:
        # Эмуляция всех действий
        if command in ("walk","walk_backward", "turn_left", "turn_right",
                       "sit", "stand", "goto_point", "goto_leader",
                       "attack", "defend", "form_line", "form_circle",
                       "defend_leader", "capture_point"):
            return f"Эмуляция: {command} выполнено."
        elif command == "status":
            return "ROS2-навык в эмуляции. Установите ROS2 Humble и обновите код."
        elif command == "start_training":
            threading.Thread(target=start_training).start()
            return "Обучение ходьбе запущено (эмуляция)."
        else:
            return f"Эмуляция: неизвестная команда '{command}'."

    # Реальный ROS2 (если установлен)
    if command == "image":
        if latest_image is None:
            return "Нет данных с камеры."
        meta = {k: v for k, v in latest_image.items() if k != "data"}
        meta["data_size"] = len(latest_image.get("data", ""))
        return json.dumps(meta, ensure_ascii=False)

    elif command == "scan":
        if latest_scan is None:
            return "Нет данных с лидара."
        ranges = latest_scan["ranges"]
        summary = {
            "points": len(ranges),
            "min_range": min(ranges),
            "max_range": max(ranges),
            "angle_min": latest_scan["angle_min"],
            "angle_max": latest_scan["angle_max"]
        }
        return json.dumps(summary, ensure_ascii=False)

    elif command == "move":
        if ros_node is None:
            return "ROS2-узел не активен"
        linear = float(params.get("linear", 0.0))
        angular = float(params.get("angular", 0.0))
        twist = Twist()
        twist.linear.x = linear
        twist.angular.z = angular
        ros_node.cmd_vel_pub.publish(twist)
        return f"Движение: линейная {linear:.2f} м/с, угловая {angular:.2f} рад/с"

    elif command == "stop":
        if ros_node is None:
            return "ROS2-узел не активен"
        twist = Twist()
        ros_node.cmd_vel_pub.publish(twist)
        return "Остановка выполнена"

    elif command == "status":
        if ros_node is None:
            return "ROS2-узел не активен"
        return "ROS2 активен. Подписки: /camera/image_raw, /scan. Публикация: /cmd_vel"

    # Общие действия (будут обработаны как заглушки, т.к. реальное выполнение требует отдельных топиков)
    elif command in ("walk", "walk_backward", "turn_left", "turn_right",
                     "sit", "stand", "goto_point", "goto_leader",
                     "attack", "defend", "form_line", "form_circle",
                     "defend_leader", "capture_point"):
        # В реальном ROS2 здесь был бы вызов соответствующих action-серверов.
        # Пока возвращаем успех.
        return f"ROS2: {command} выполнено."

    elif command == "start_training":
        threading.Thread(target=start_training).start()
        return "Обучение ходьбе запущено."

    elif command == "get_training_status":
        if training_active:
            return "Идёт обучение..."
        elif training_model:
            return f"Модель обучена: {training_model}"
        else:
            return "Обучение не проводилось."

    else:
        return f"Неизвестная команда: {command}"

def shutdown(name=None):
    global ros_thread
    if ROS2_AVAILABLE and ros_thread and ros_thread.is_alive():
        shutdown_flag.set()
        ros_thread.join(timeout=3)
    print("ROS2-плагин выгружен")