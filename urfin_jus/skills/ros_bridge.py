# skills/ros_bridge.py
from __future__ import annotations

import sys
import os
import json
import threading
import logging
import time
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple, Callable

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROS2_AVAILABLE = False
try:
    import rclpy
    from rclpy.node import Node
    from rclpy.action import ActionClient
    from rclpy.executors import MultiThreadedExecutor
    from sensor_msgs.msg import JointState
    from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint
    from control_msgs.action import FollowJointTrajectory
    from builtin_interfaces.msg import Duration as BuiltinDuration
    from geometry_msgs.msg import Twist, Pose, Point
    from nav_msgs.msg import Odometry
    from std_msgs.msg import String
    ROS2_AVAILABLE = True
except ImportError:
    ROS2_AVAILABLE = False

# Если ROS2 не доступен, создаём фиктивные классы-заглушки,
# чтобы определения классов ниже не вызывали NameError.
if not ROS2_AVAILABLE:
    class Node:
        pass
    class ActionClient:
        pass
    class MultiThreadedExecutor:
        pass
    class JointState:
        pass
    class JointTrajectory:
        pass
    class JointTrajectoryPoint:
        pass
    class FollowJointTrajectory:
        pass
    class BuiltinDuration:
        pass
    class Twist:
        pass
    class Pose:
        pass
    class Point:
        pass
    class Odometry:
        pass
    class String:
        pass

logger = logging.getLogger(__name__)

DEFAULT_JOINTS = {
    "robot": [
        "front_left_hip", "front_left_thigh", "front_left_calf",
        "front_right_hip", "front_right_thigh", "front_right_calf",
        "rear_left_hip", "rear_left_thigh", "rear_left_calf",
        "rear_right_hip", "rear_right_thigh", "rear_right_calf"
    ],
    "drone": [],
    "gladio_bot": [
        "base_joint", "shoulder_pan", "shoulder_lift",
        "elbow", "wrist_1", "wrist_2", "wrist_3"
    ],
}

@dataclass
class RobotState:
    id: str
    type: str
    position: Dict[str, float]
    orientation: Dict[str, float]
    angle: float = 0.0
    health: int = 100
    team: Optional[str] = None
    is_leader: bool = False
    is_flying: bool = False
    joint_names: List[str] = field(default_factory=list)
    node: Optional[Node] = None
    connected: bool = False

class RobotControlNode(Node):
    def __init__(self, robot_id: str, joint_names: List[str], namespace: str = ""):
        # Если ROS2 недоступен, вызываем конструктор родительского класса-заглушки
        super().__init__(f'robot_control_{robot_id}', namespace=namespace)
        self.robot_id = robot_id
        self.joint_names = joint_names if joint_names else []
        self.lock = threading.Lock()
        self.current_positions = [0.0] * len(self.joint_names)
        self.current_velocities = [0.0] * len(self.joint_names)
        self.current_efforts = [0.0] * len(self.joint_names)
        self.state_received = False
        self.odom_pose = Pose()
        self.odom_twist = Twist()

        if self.joint_names and ROS2_AVAILABLE:
            self.subscription = self.create_subscription(
                JointState,
                '/joint_states',
                self.joint_state_callback,
                10
            )
            self.command_publisher = self.create_publisher(
                JointTrajectory,
                f'/{robot_id}/joint_trajectory_controller/command',
                10
            )
            self.action_client = ActionClient(
                self,
                FollowJointTrajectory,
                f'/{robot_id}/joint_trajectory_controller/follow_joint_trajectory'
            )
        else:
            self.subscription = None
            self.command_publisher = None
            self.action_client = None

        self.cmd_vel_pub = self.create_publisher(Twist, f'/{robot_id}/cmd_vel', 10)
        self.odom_sub = self.create_subscription(
            Odometry,
            f'/{robot_id}/odom',
            self.odom_callback,
            10
        )
        logger.info(f"ROS2-узел для {robot_id} создан. Joints: {self.joint_names or 'нет (cmd_vel)'}")

    def joint_state_callback(self, msg: JointState):
        if not ROS2_AVAILABLE:
            return
        with self.lock:
            for i, name in enumerate(self.joint_names):
                if name in msg.name:
                    idx = msg.name.index(name)
                    if idx < len(msg.position):
                        self.current_positions[i] = msg.position[idx]
                    if idx < len(msg.velocity):
                        self.current_velocities[i] = msg.velocity[idx]
                    if idx < len(msg.effort):
                        self.current_efforts[i] = msg.effort[idx]
            self.state_received = True

    def odom_callback(self, msg: Odometry):
        if not ROS2_AVAILABLE:
            return
        self.odom_pose = msg.pose.pose
        self.odom_twist = msg.twist.twist

    def get_current_positions(self) -> List[float]:
        with self.lock:
            return self.current_positions.copy()

    def send_trajectory(self, positions: List[float],
                        velocities: Optional[List[float]] = None,
                        duration: float = 1.0) -> bool:
        if not ROS2_AVAILABLE or not self.action_client or len(positions) != len(self.joint_names):
            logger.error(f"Некорректный запрос траектории для {self.robot_id}")
            return False
        goal = FollowJointTrajectory.Goal()
        goal.trajectory.joint_names = self.joint_names
        point = JointTrajectoryPoint()
        point.positions = positions
        if velocities and len(velocities) == len(positions):
            point.velocities = velocities
        sec = int(duration)
        nanosec = int((duration - sec) * 1e9)
        point.time_from_start = BuiltinDuration(sec=sec, nanosec=nanosec)
        goal.trajectory.points.append(point)

        if not self.action_client.wait_for_server(timeout_sec=2.0):
            logger.warning(f"Action server для {self.robot_id} не отвечает")
            return False
        send_goal_future = self.action_client.send_goal_async(goal)
        send_goal_future.add_done_callback(self._goal_response_callback)
        return True

    def _goal_response_callback(self, future):
        goal_handle = future.result()
        if not goal_handle.accepted:
            logger.error(f"Цель для {self.robot_id} отклонена")
            return
        get_result_future = goal_handle.get_result_async()
        get_result_future.add_done_callback(
            lambda f: logger.info(f"Траектория для {self.robot_id} завершена")
        )

    def send_cmd_vel(self, linear: float, angular: float):
        if not ROS2_AVAILABLE:
            return
        twist = Twist()
        twist.linear.x = float(linear)
        twist.angular.z = float(angular)
        self.cmd_vel_pub.publish(twist)

    def get_odometry(self) -> Tuple[Pose, Twist]:
        return self.odom_pose, self.odom_twist

    def cleanup(self):
        if ROS2_AVAILABLE:
            self.destroy_node()
        logger.info(f"Узел {self.robot_id} удалён")

class RosBridge:
    def __init__(self):
        self.robots: Dict[str, RobotState] = {}
        self.lock = threading.Lock()
        self.initialized = False
        self.executor = None
        self.ros_thread = None
        self.shutdown_flag = threading.Event()
        self.sim_mode = not ROS2_AVAILABLE
        self._emit_callback: Optional[Callable] = None

    def init(self, emit_callback: Optional[Callable] = None) -> bool:
        if self.initialized:
            return True
        self._emit_callback = emit_callback
        if not ROS2_AVAILABLE:
            logger.warning("ROS2 не найден! Работаем в режиме симуляции.")
            self.sim_mode = True
            self.initialized = True
            return True
        try:
            rclpy.init()
            self.executor = MultiThreadedExecutor()
            self.ros_thread = threading.Thread(target=self._ros_spin, daemon=True)
            self.ros_thread.start()
            self.initialized = True
            logger.info("ROS2 инициализирован в фоновом потоке")
            return True
        except Exception as e:
            logger.exception(f"Ошибка инициализации ROS2: {e}")
            self.sim_mode = True
            self.initialized = True
            return True

    def _ros_spin(self):
        try:
            while not self.shutdown_flag.is_set():
                with self.lock:
                    current_nodes = [r.node for r in self.robots.values() if r.node is not None]
                for node in current_nodes:
                    if node not in self.executor._nodes:
                        self.executor.add_node(node)
                self.executor.spin_once(timeout_sec=0.1)
        except Exception as e:
            logger.exception(f"Ошибка в потоке ROS: {e}")
        finally:
            if rclpy.ok():
                rclpy.shutdown()

    def register_robot(self, robot_id: str, robot_type: str,
                       urdf_path: Optional[str] = None,
                       position: Optional[Dict[str, float]] = None) -> bool:
        with self.lock:
            if robot_id in self.robots:
                logger.warning(f"Робот {robot_id} уже зарегистрирован")
                return False
            joint_names = DEFAULT_JOINTS.get(robot_type, [])
            node = None
            if not self.sim_mode:
                try:
                    node = RobotControlNode(robot_id, joint_names)
                except Exception as e:
                    logger.error(f"Не удалось создать узел для {robot_id}: {e}")
                    node = None
            state = RobotState(
                id=robot_id,
                type=robot_type,
                position=position or {"x": 0.0, "y": 0.0, "z": 0.0},
                orientation={"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
                joint_names=joint_names,
                node=node,
                connected=not self.sim_mode,
                is_flying=(robot_type == "drone")
            )
            self.robots[robot_id] = state
            logger.info(f"Робот {robot_id} ({robot_type}) зарегистрирован (режим: {'реальный' if not self.sim_mode else 'симуляция'})")
            return True

    def unregister_robot(self, robot_id: str) -> bool:
        with self.lock:
            if robot_id not in self.robots:
                return False
            state = self.robots[robot_id]
            if state.node and self.executor:
                try:
                    self.executor.remove_node(state.node)
                except Exception:
                    pass
                state.node.cleanup()
            del self.robots[robot_id]
            logger.info(f"Робот {robot_id} удалён")
            return True

    def get_robot(self, robot_id: str) -> Optional[RobotState]:
        with self.lock:
            return self.robots.get(robot_id)

    def get_all_robots(self) -> List[RobotState]:
        with self.lock:
            return list(self.robots.values())

    def send_joint_command(self, robot_id: str, positions: List[float],
                           velocities: Optional[List[float]] = None,
                           duration: float = 1.0) -> bool:
        state = self.get_robot(robot_id)
        if not state or not state.node:
            return False
        return state.node.send_trajectory(positions, velocities, duration)

    def send_cmd_vel(self, robot_id: str, linear: float, angular: float) -> bool:
        with self.lock:
            state = self.robots.get(robot_id)
            if not state:
                return False
            if state.node and not self.sim_mode:
                state.node.send_cmd_vel(linear, angular)
                return True
            else:
                # Симуляция
                angle = state.angle
                if angular != 0:
                    angle += angular * 0.1
                new_x = state.position["x"] + linear * 0.1 * math.cos(angle)
                new_z = state.position["z"] + linear * 0.1 * math.sin(angle)
                state.position["x"] = new_x
                state.position["z"] = new_z
                state.angle = angle
                if self._emit_callback:
                    try:
                        self._emit_callback('robot_position_update', {
                            'robot_id': robot_id,
                            'position': state.position,
                            'angle': angle
                        })
                    except Exception as e:
                        logger.error(f"Ошибка отправки обновления позиции: {e}")
                return True

    def get_odometry(self, robot_id: str) -> Optional[Tuple[Dict, Dict]]:
        state = self.get_robot(robot_id)
        if not state:
            return None
        if state.node and not self.sim_mode:
            pose, twist = state.node.get_odometry()
            pose_dict = {
                "position": {"x": pose.position.x, "y": pose.position.y, "z": pose.position.z},
                "orientation": {"x": pose.orientation.x, "y": pose.orientation.y,
                                "z": pose.orientation.z, "w": pose.orientation.w}
            }
            twist_dict = {
                "linear": {"x": twist.linear.x, "y": twist.linear.y, "z": twist.linear.z},
                "angular": {"x": twist.angular.x, "y": twist.angular.y, "z": twist.angular.z}
            }
            return pose_dict, twist_dict
        else:
            pose_dict = {
                "position": state.position,
                "orientation": state.orientation
            }
            twist_dict = {
                "linear": {"x": 0.0, "y": 0.0, "z": 0.0},
                "angular": {"x": 0.0, "y": 0.0, "z": 0.0}
            }
            return pose_dict, twist_dict

    def connect_real(self, robot_id: str, ip: str, port: int = 9090) -> bool:
        with self.lock:
            if robot_id not in self.robots:
                logger.error(f"Робот {robot_id} не зарегистрирован")
                return False
            state = self.robots[robot_id]
            state.connected = True
            logger.info(f"Реальный робот {robot_id} подключён к {ip}:{port}")
            return True

    def shutdown(self):
        self.shutdown_flag.set()
        with self.lock:
            for state in self.robots.values():
                if state.node:
                    state.node.cleanup()
            self.robots.clear()
        if self.ros_thread:
            self.ros_thread.join(timeout=2)
        logger.info("ROS-мост завершён")

bridge = RosBridge()

def init(name: str, emit_callback: Optional[Callable] = None) -> None:
    if not bridge.init(emit_callback):
        raise RuntimeError("Не удалось инициализировать ROS-мост")
    logger.info(f"ROS-мост '{name}' готов")

def handle_message(message: str) -> str:
    try:
        data = json.loads(message)
    except json.JSONDecodeError:
        return json.dumps({"error": "Неверный формат JSON"})

    command = data.get("command")
    robot_id = data.get("robot_id")
    params = data.get("params", {})

    def require_robot_id():
        if not robot_id:
            raise ValueError("Не указан robot_id")

    try:
        if command == "register_robot":
            require_robot_id()
            robot_type = params.get("type", "unknown")
            urdf_path = params.get("urdf_path")
            position = params.get("position")
            success = bridge.register_robot(robot_id, robot_type, urdf_path, position)
            return json.dumps({"status": "ok" if success else "error"})

        elif command == "unregister_robot":
            require_robot_id()
            success = bridge.unregister_robot(robot_id)
            return json.dumps({"status": "ok" if success else "error"})

        elif command == "send_joint_command":
            require_robot_id()
            positions = params.get("positions")
            if not positions or not isinstance(positions, list):
                return json.dumps({"error": "positions должен быть списком"})
            velocities = params.get("velocities")
            duration = float(params.get("duration", 1.0))
            success = bridge.send_joint_command(robot_id, positions, velocities, duration)
            return json.dumps({"status": "ok" if success else "error"})

        elif command == "send_cmd_vel":
            require_robot_id()
            linear = float(params.get("linear", 0.0))
            angular = float(params.get("angular", 0.0))
            success = bridge.send_cmd_vel(robot_id, linear, angular)
            return json.dumps({"status": "ok" if success else "error"})

        elif command == "get_odometry":
            require_robot_id()
            odom = bridge.get_odometry(robot_id)
            if odom is None:
                return json.dumps({"error": "Робот не найден или нет одометрии"})
            return json.dumps({"pose": odom[0], "twist": odom[1]})

        elif command == "get_robot":
            require_robot_id()
            state = bridge.get_robot(robot_id)
            if not state:
                return json.dumps({"error": "Робот не найден"})
            return json.dumps({
                "id": state.id,
                "type": state.type,
                "position": state.position,
                "orientation": state.orientation,
                "angle": state.angle,
                "health": state.health,
                "team": state.team,
                "is_leader": state.is_leader,
                "is_flying": state.is_flying,
                "connected": state.connected
            })

        elif command == "get_all_robots":
            robots = bridge.get_all_robots()
            return json.dumps([{
                "id": r.id,
                "type": r.type,
                "position": r.position,
                "health": r.health,
                "team": r.team,
                "is_leader": r.is_leader,
                "is_flying": r.is_flying,
                "connected": r.connected
            } for r in robots])

        elif command == "connect_real":
            require_robot_id()
            ip = params.get("ip")
            port = params.get("port", 9090)
            if not ip:
                return json.dumps({"error": "Не указан IP"})
            success = bridge.connect_real(robot_id, ip, port)
            return json.dumps({"status": "ok" if success else "error"})

        elif command == "shutdown":
            bridge.shutdown()
            return json.dumps({"status": "ok", "message": "Мост завершён"})

        else:
            return json.dumps({"error": f"Неизвестная команда: {command}"})

    except Exception as e:
        logger.exception("Ошибка обработки сообщения")
        return json.dumps({"error": str(e)})

def shutdown(name: Optional[str] = None) -> None:
    bridge.shutdown()
    logger.info("ROS-мост выгружен")