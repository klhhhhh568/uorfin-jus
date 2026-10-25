# skills/ros2_skill.py
import sys, os, json, threading, logging, math, time
from typing import Optional, Dict, Any, List

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import skills.ros_bridge as ros_bridge
import skills.cerebellum_skill as cerebellum_skill

logger = logging.getLogger(__name__)

_simulation_robots: Dict[str, Dict[str, Any]] = {}
_teams: Dict[str, List[str]] = {}
_emit_callback = None
_lock = threading.RLock()

def init(name: str, emit_callback=None) -> None:
    global _emit_callback
    _emit_callback = emit_callback
    ros_bridge.init("RosBridge")
    cerebellum_skill.init("Cerebellum")
    logger.info(f"ROS2-навык '{name}' инициализирован")

def _emit(event: str, data: dict) -> None:
    if _emit_callback:
        try:
            _emit_callback(event, data)
        except Exception as e:
            logger.error(f"Ошибка отправки события {event}: {e}")

def _get_robot(robot_id: str) -> Optional[Dict]:
    with _lock:
        return _simulation_robots.get(robot_id)

def _update_robot(robot_id: str, updates: Dict) -> None:
    with _lock:
        if robot_id in _simulation_robots:
            _simulation_robots[robot_id].update(updates)

def handle_message(message: str) -> str:
    try:
        data = json.loads(message)
    except json.JSONDecodeError:
        return json.dumps({"error": "Неверный формат JSON"})

    command = data.get("command", "").lower()
    robot_id = data.get("robot_id")
    params = data.get("params", {})

    try:
        # ---- Регистрация и удаление ----
        if command == "register_robot":
            if not robot_id:
                return json.dumps({"error": "Не указан robot_id"})
            robot_type = params.get("type", "unknown")
            urdf_path = params.get("urdf_path")
            position = params.get("position", {"x": 0.0, "y": 0.0, "z": 0.0})
            success = ros_bridge.bridge.register_robot(robot_id, robot_type, urdf_path, position)
            if success:
                with _lock:
                    _simulation_robots[robot_id] = {
                        "id": robot_id,
                        "type": robot_type,
                        "position": position,
                        "angle": 0.0,
                        "health": 100,
                        "team": params.get("team"),
                        "is_leader": False,
                        "is_flying": (robot_type == "drone"),
                        "is_sitting": False,
                        "is_moving": False,
                        "is_turning": False,
                        "has_target": False,
                        "battery": 100,
                        "connected": False
                    }
                _emit("robot_response", {"robot_id": robot_id, "text": f"Робот {robot_id} зарегистрирован"})
            return json.dumps({"status": "ok" if success else "error"})

        elif command == "unregister_robot":
            if not robot_id:
                return json.dumps({"error": "Не указан robot_id"})
            success = ros_bridge.bridge.unregister_robot(robot_id)
            with _lock:
                _simulation_robots.pop(robot_id, None)
                for team in _teams.values():
                    if robot_id in team:
                        team.remove(robot_id)
            return json.dumps({"status": "ok" if success else "error"})

        # ---- Движение ----
        elif command in ("move_forward", "move_backward", "turn_left", "turn_right", "stop"):
            if not robot_id:
                return json.dumps({"error": "Не указан robot_id"})
            speed = float(params.get("speed", 0.5))
            angular = float(params.get("angular", 0.5))
            if command == "move_forward":
                ros_bridge.bridge.send_cmd_vel(robot_id, speed, 0.0)
                _update_robot(robot_id, {"is_moving": True})
            elif command == "move_backward":
                ros_bridge.bridge.send_cmd_vel(robot_id, -speed, 0.0)
                _update_robot(robot_id, {"is_moving": True})
            elif command == "turn_left":
                ros_bridge.bridge.send_cmd_vel(robot_id, 0.0, angular)
                _update_robot(robot_id, {"is_turning": True})
            elif command == "turn_right":
                ros_bridge.bridge.send_cmd_vel(robot_id, 0.0, -angular)
                _update_robot(robot_id, {"is_turning": True})
            elif command == "stop":
                ros_bridge.bridge.send_cmd_vel(robot_id, 0.0, 0.0)
                _update_robot(robot_id, {"is_moving": False, "is_turning": False})
            return json.dumps({"status": "ok"})

        # ---- Взлёт/посадка ----
        elif command == "takeoff":
            if not robot_id:
                return json.dumps({"error": "Не указан robot_id"})
            robot = _get_robot(robot_id)
            if robot and robot.get("is_flying"):
                _update_robot(robot_id, {"is_flying": True, "is_moving": False})
                ros_bridge.bridge.send_cmd_vel(robot_id, 0.0, 0.0)
                _emit("robot_response", {"robot_id": robot_id, "text": "🛫 Взлёт"})
                return json.dumps({"status": "ok"})
            else:
                return json.dumps({"error": "Робот не является дроном или уже в воздухе"})

        elif command == "land":
            if not robot_id:
                return json.dumps({"error": "Не указан robot_id"})
            robot = _get_robot(robot_id)
            if robot and robot.get("is_flying"):
                _update_robot(robot_id, {"is_flying": False})
                ros_bridge.bridge.send_cmd_vel(robot_id, 0.0, 0.0)
                _emit("robot_response", {"robot_id": robot_id, "text": "🛬 Посадка"})
                return json.dumps({"status": "ok"})
            else:
                return json.dumps({"error": "Робот не в воздухе"})

        # ---- Сидеть/встать ----
        elif command == "sit":
            if not robot_id:
                return json.dumps({"error": "Не указан robot_id"})
            robot = _get_robot(robot_id)
            if robot and robot.get("type") == "robot":
                ros_bridge.bridge.send_joint_command(robot_id, [0.8]*12, duration=2.0)
                _update_robot(robot_id, {"is_sitting": True})
                _emit("robot_animate", {"robot_id": robot_id, "action": "sit", "value": 1})
                return json.dumps({"status": "ok"})
            else:
                return json.dumps({"error": "Робот не поддерживает сидение"})

        elif command == "stand":
            if not robot_id:
                return json.dumps({"error": "Не указан robot_id"})
            robot = _get_robot(robot_id)
            if robot and robot.get("type") == "robot":
                ros_bridge.bridge.send_joint_command(robot_id, [0.0]*12, duration=2.0)
                _update_robot(robot_id, {"is_sitting": False})
                _emit("robot_animate", {"robot_id": robot_id, "action": "stand", "value": 1})
                return json.dumps({"status": "ok"})
            else:
                return json.dumps({"error": "Робот не поддерживает стояние"})

        # ---- Атака ----
        elif command == "attack":
            if not robot_id:
                return json.dumps({"error": "Не указан robot_id"})
            target = params.get("target")
            _update_robot(robot_id, {"has_target": True})
            _emit("robot_animate", {
                "robot_id": robot_id,
                "action": "attack",
                "value": 1,
                "target": target
            })
            return json.dumps({"status": "ok"})

        # ---- Выполнение текстовой команды ----
        elif command == "execute":
            if not robot_id:
                return json.dumps({"error": "Не указан robot_id"})
            cmd_text = params.get("cmd", "").strip()
            if not cmd_text:
                return json.dumps({"error": "Пустая команда"})
            result_text = _execute_text_command(robot_id, cmd_text)
            _emit("robot_response", {"robot_id": robot_id, "text": result_text})
            return json.dumps({"status": "ok", "message": result_text})

        # ---- Выполнение цели через cerebellum ----
        elif command == "execute_goal":
            if not robot_id:
                return json.dumps({"error": "Не указан robot_id"})
            goal = params.get("goal", {})
            if not goal:
                return json.dumps({"error": "Не указана цель"})
            robot = _get_robot(robot_id)
            if not robot:
                return json.dumps({"error": "Робот не найден"})
            current_state = {
                "is_moving": robot.get("is_moving", False),
                "is_sitting": robot.get("is_sitting", False),
                "is_flying": robot.get("is_flying", False),
                "has_target": robot.get("has_target", False),
                "is_turning": robot.get("is_turning", False),
            }
            plan = cerebellum_skill.handle_message(json.dumps({
                "command": "plan",
                "robot_id": robot_id,
                "current_state": current_state,
                "goal_state": goal
            }))
            try:
                plan_data = json.loads(plan)
                actions = plan_data.get("plan", [])
                if not actions:
                    return json.dumps({"error": "План не найден"})
                _execute_plan(robot_id, actions)
                return json.dumps({"status": "ok", "plan": actions})
            except Exception as e:
                return json.dumps({"error": f"Ошибка планирования: {str(e)}"})

        # ---- Команды для работы с командами (TEAMS) ----
        elif command == "create_team":
            team_name = params.get("team_name")
            if not team_name:
                return json.dumps({"error": "Не указано имя команды"})
            with _lock:
                if team_name in _teams:
                    return json.dumps({"error": f"Команда {team_name} уже существует"})
                _teams[team_name] = []
            _emit("team_created", {"team": team_name})
            return json.dumps({"status": "ok", "team": team_name})

        elif command == "add_to_team":
            team_name = params.get("team")
            robot_id_to_add = params.get("robot_id") or robot_id
            if not team_name or not robot_id_to_add:
                return json.dumps({"error": "Не указаны team и robot_id"})
            with _lock:
                if team_name not in _teams:
                    return json.dumps({"error": f"Команда {team_name} не найдена"})
                if robot_id_to_add not in _simulation_robots:
                    return json.dumps({"error": f"Робот {robot_id_to_add} не зарегистрирован"})
                if robot_id_to_add not in _teams[team_name]:
                    _teams[team_name].append(robot_id_to_add)
                    _update_robot(robot_id_to_add, {"team": team_name})
            _emit("robot_added_to_team", {"robot_id": robot_id_to_add, "team": team_name})
            return json.dumps({"status": "ok"})

        elif command == "remove_from_team":
            team_name = params.get("team")
            robot_id_to_remove = params.get("robot_id") or robot_id
            if not team_name or not robot_id_to_remove:
                return json.dumps({"error": "Не указаны team и robot_id"})
            with _lock:
                if team_name not in _teams:
                    return json.dumps({"error": f"Команда {team_name} не найдена"})
                if robot_id_to_remove in _teams[team_name]:
                    _teams[team_name].remove(robot_id_to_remove)
                    _update_robot(robot_id_to_remove, {"team": None})
            return json.dumps({"status": "ok"})

        elif command == "set_leader":
            team_name = params.get("team")
            leader_id = params.get("robot_id") or robot_id
            if not team_name or not leader_id:
                return json.dumps({"error": "Не указаны team и robot_id"})
            with _lock:
                if team_name not in _teams:
                    return json.dumps({"error": f"Команда {team_name} не найдена"})
                if leader_id not in _simulation_robots:
                    return json.dumps({"error": f"Робот {leader_id} не зарегистрирован"})
                for rid in _teams[team_name]:
                    _update_robot(rid, {"is_leader": False})
                _update_robot(leader_id, {"is_leader": True})
            _emit("leader_set", {"team": team_name, "leader": leader_id})
            return json.dumps({"status": "ok", "leader": leader_id})

        elif command == "get_leader_thoughts":
            team_name = params.get("team")
            if not team_name:
                return json.dumps({"error": "Не указана команда"})
            with _lock:
                leader_id = None
                for rid in _teams.get(team_name, []):
                    if _simulation_robots.get(rid, {}).get("is_leader"):
                        leader_id = rid
                        break
                if not leader_id:
                    return json.dumps({"error": f"В команде {team_name} нет лидера"})
                thoughts = {
                    "leader": leader_id,
                    "plan": "Текущий план: двигаться к точке А, затем атаковать",
                    "goals": {"x": 10, "y": 5}
                }
            return json.dumps(thoughts)

        elif command == "request_reinforcements":
            team_name = params.get("team")
            if not team_name:
                return json.dumps({"error": "Не указана команда"})
            new_id = f"reinforcement_{int(time.time())}"
            with _lock:
                robot_type = params.get("type", "robot")
                position = params.get("position", {"x": 0, "y": 0, "z": 0})
                success = ros_bridge.bridge.register_robot(new_id, robot_type, None, position)
                if not success:
                    return json.dumps({"error": "Не удалось создать подмогу"})
                _simulation_robots[new_id] = {
                    "id": new_id,
                    "type": robot_type,
                    "position": position,
                    "health": 100,
                    "team": team_name,
                    "is_leader": False,
                    "is_flying": (robot_type == "drone"),
                    "is_sitting": False,
                    "is_moving": False,
                    "has_target": False,
                    "battery": 100,
                    "connected": False
                }
                if team_name in _teams:
                    _teams[team_name].append(new_id)
                else:
                    _teams[team_name] = [new_id]
            _emit("reinforcement_arrived", {"robot_id": new_id, "team": team_name})
            return json.dumps({"status": "ok", "new_robot_id": new_id})

        elif command == "connect_real_robot":
            real_robot_id = params.get("robot_id") or robot_id
            ip = params.get("ip")
            port = params.get("port", 9090)
            if not real_robot_id or not ip:
                return json.dumps({"error": "Не указаны robot_id и ip"})
            success = ros_bridge.bridge.connect_real(real_robot_id, ip, port)
            if success:
                with _lock:
                    if real_robot_id in _simulation_robots:
                        _simulation_robots[real_robot_id]["connected"] = True
                _emit("real_robot_connected", {"robot_id": real_robot_id, "ip": ip})
                return json.dumps({"status": "ok", "message": f"Робот {real_robot_id} подключён к {ip}:{port}"})
            else:
                return json.dumps({"error": "Не удалось подключиться к реальному роботу"})

        # ---- Нанесение урона ----
        elif command == "damage_robot":
            if not robot_id:
                return json.dumps({"error": "Не указан robot_id"})
            damage = params.get("damage", 0)
            with _lock:
                robot = _simulation_robots.get(robot_id)
                if robot:
                    robot["health"] = max(0, robot["health"] - damage)
                    if robot["health"] <= 0:
                        _emit("robot_dead", {"robot_id": robot_id, "team": robot.get("team")})
            return json.dumps({"status": "ok"})

        # ---- Получение списка роботов ----
        elif command == "get_all_robots":
            with _lock:
                robots_list = []
                for rid, r in _simulation_robots.items():
                    robots_list.append({
                        "id": rid,
                        "type": r.get("type"),
                        "position": r.get("position"),
                        "health": r.get("health"),
                        "team": r.get("team"),
                        "is_leader": r.get("is_leader"),
                        "is_flying": r.get("is_flying"),
                        "is_sitting": r.get("is_sitting"),
                        "is_moving": r.get("is_moving"),
                        "battery": r.get("battery", 100),
                        "connected": r.get("connected", False)
                    })
                return json.dumps(robots_list)

        # ---- Получение одного робота ----
        elif command == "get_robot":
            if not robot_id:
                return json.dumps({"error": "Не указан robot_id"})
            with _lock:
                r = _simulation_robots.get(robot_id)
                if not r:
                    return json.dumps({"error": "Робот не найден"})
                return json.dumps({
                    "id": r.get("id"),
                    "type": r.get("type"),
                    "position": r.get("position"),
                    "health": r.get("health"),
                    "team": r.get("team"),
                    "is_leader": r.get("is_leader"),
                    "is_flying": r.get("is_flying"),
                    "is_sitting": r.get("is_sitting"),
                    "is_moving": r.get("is_moving"),
                    "battery": r.get("battery", 100),
                    "connected": r.get("connected", False)
                })

        # ---- Обновление позиции ----
        elif command == "update_position":
            if not robot_id:
                return json.dumps({"error": "Не указан robot_id"})
            pos = params.get("position")
            if not pos:
                return json.dumps({"error": "Не указана позиция"})
            _update_robot(robot_id, {"position": pos})
            return json.dumps({"status": "ok"})

        else:
            return json.dumps({"error": f"Неизвестная команда: {command}"})

    except Exception as e:
        logger.exception("Ошибка обработки сообщения в ros2_skill")
        return json.dumps({"error": str(e)})

def _execute_text_command(robot_id: str, command: str) -> str:
    parts = command.lower().split()
    cmd = parts[0] if parts else ""
    robot = _get_robot(robot_id)
    if not robot:
        return "Робот не найден"
    if cmd in ("вперёд", "forward"):
        ros_bridge.bridge.send_cmd_vel(robot_id, 0.5, 0.0)
        _update_robot(robot_id, {"is_moving": True})
        return "Движение вперёд"
    elif cmd in ("назад", "backward"):
        ros_bridge.bridge.send_cmd_vel(robot_id, -0.5, 0.0)
        _update_robot(robot_id, {"is_moving": True})
        return "Движение назад"
    elif cmd in ("стоп", "stop"):
        ros_bridge.bridge.send_cmd_vel(robot_id, 0.0, 0.0)
        _update_robot(robot_id, {"is_moving": False, "is_turning": False})
        return "Остановлен"
    elif cmd == "сесть":
        if robot.get("type") == "robot":
            ros_bridge.bridge.send_joint_command(robot_id, [0.8]*12, duration=2.0)
            _update_robot(robot_id, {"is_sitting": True})
            _emit("robot_animate", {"robot_id": robot_id, "action": "sit", "value": 1})
            return "Садится"
    elif cmd == "встать":
        if robot.get("type") == "robot":
            ros_bridge.bridge.send_joint_command(robot_id, [0.0]*12, duration=2.0)
            _update_robot(robot_id, {"is_sitting": False})
            _emit("robot_animate", {"robot_id": robot_id, "action": "stand", "value": 1})
            return "Встаёт"
    elif cmd == "атаковать" or cmd == "attack":
        target = parts[1] if len(parts) > 1 else None
        _update_robot(robot_id, {"has_target": True})
        _emit("robot_animate", {"robot_id": robot_id, "action": "attack", "value": 1, "target": target})
        return f"Атака цели {target}" if target else "Атака"
    elif cmd == "взлететь" or cmd == "takeoff":
        if robot.get("is_flying"):
            _update_robot(robot_id, {"is_flying": True})
            ros_bridge.bridge.send_cmd_vel(robot_id, 0.0, 0.0)
            return "Взлёт"
    elif cmd == "приземлиться" or cmd == "land":
        if robot.get("is_flying"):
            _update_robot(robot_id, {"is_flying": False})
            ros_bridge.bridge.send_cmd_vel(robot_id, 0.0, 0.0)
            return "Посадка"
    else:
        return f"Неизвестная команда: {command}"

def _execute_plan(robot_id: str, actions: List[str]) -> None:
    def run():
        for action in actions:
            logger.info(f"Выполнение действия {action} для {robot_id}")
            time.sleep(0.5)
            _emit("robot_response", {"robot_id": robot_id, "text": f"Выполнено: {action}"})
    threading.Thread(target=run, daemon=True).start()

def shutdown(name: Optional[str] = None) -> None:
    ros_bridge.shutdown()
    logger.info("ROS2-навык выгружен")