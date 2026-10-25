# skills/cerebellum_skill.py
import json
import logging
from typing import List, Dict, Any, Optional, Tuple
from collections import deque

logger = logging.getLogger(__name__)


class CerebellumPlanner:
    """
    Планировщик действий для роботов на основе поиска в ширину (BFS).
    Используется для построения последовательности действий, ведущей из текущего состояния в целевое.
    """

    def __init__(self):
        self.actions: List[Dict[str, Any]] = []
        self.agent_states: Dict[str, Dict[str, Any]] = {}

    def add_action(self, name: str, preconditions: Dict[str, Any],
                   effects: Dict[str, Any], cost: int = 1) -> None:
        """
        Добавить действие с предусловиями и эффектами.

        :param name: имя действия (должно быть уникальным)
        :param preconditions: словарь условий, которые должны быть истинны перед выполнением
        :param effects: словарь изменений состояния после выполнения
        :param cost: стоимость действия (для A* пока не используется, но оставлено для совместимости)
        """
        if not isinstance(preconditions, dict) or not isinstance(effects, dict):
            raise TypeError("Предусловия и эффекты должны быть словарями")
        self.actions.append({
            "name": name,
            "pre": preconditions.copy(),
            "eff": effects.copy(),
            "cost": cost
        })
        logger.info("Добавлено действие '%s': pre=%s, eff=%s", name, preconditions, effects)

    def add_actions(self, actions: List[Dict[str, Any]]) -> None:
        """
        Массовое добавление действий.

        :param actions: список словарей с ключами name, pre, eff, cost (опционально)
        """
        for action in actions:
            self.add_action(
                name=action["name"],
                preconditions=action.get("pre", {}),
                effects=action.get("eff", {}),
                cost=action.get("cost", 1)
            )

    def _applicable(self, action: Dict[str, Any], state: Dict[str, Any]) -> bool:
        """Проверяет, выполнены ли все предусловия действия в данном состоянии."""
        for key, value in action["pre"].items():
            if state.get(key) != value:
                return False
        return True

    def _apply_effects(self, state: Dict[str, Any], effects: Dict[str, Any]) -> Dict[str, Any]:
        """Возвращает новое состояние после применения эффектов (не изменяет исходное)."""
        new_state = state.copy()
        new_state.update(effects)
        return new_state

    def _state_matches_goal(self, state: Dict[str, Any], goal: Dict[str, Any]) -> bool:
        """Проверяет, что все целевые условия выполнены в состоянии."""
        for key, value in goal.items():
            if state.get(key) != value:
                return False
        return True

    def plan(self, current_state: Dict[str, Any], goal_state: Dict[str, Any]) -> Optional[List[str]]:
        """
        Поиск последовательности действий, ведущей из current_state в goal_state.
        Используется алгоритм BFS. Возвращает список имён действий или None, если план не найден.
        """
        # Очередь: (состояние, путь)
        queue = deque()
        queue.append((current_state.copy(), []))
        visited = set()

        def state_key(s):
            return tuple(sorted(s.items()))

        visited.add(state_key(current_state))

        while queue:
            state, path = queue.popleft()
            if self._state_matches_goal(state, goal_state):
                logger.info("План найден: %s", path)
                return path

            for action in self.actions:
                if self._applicable(action, state):
                    new_state = self._apply_effects(state, action["eff"])
                    sk = state_key(new_state)
                    if sk not in visited:
                        visited.add(sk)
                        queue.append((new_state, path + [action["name"]]))

        logger.warning("План не найден для цели %s из состояния %s", goal_state, current_state)
        return None

    def plan_for_robot(self, robot_id: str, goal_state: Dict[str, Any],
                       current_state: Optional[Dict[str, Any]] = None) -> Optional[List[str]]:
        """
        Построить план для конкретного робота.

        :param robot_id: идентификатор робота
        :param goal_state: целевое состояние
        :param current_state: если передано, используется вместо сохранённого состояния
        """
        if current_state is None:
            current = self.agent_states.get(robot_id, {})
        else:
            current = current_state
            # Обновляем сохранённое состояние, чтобы оно было актуальным
            self.update_state(robot_id, current, merge=False)
        return self.plan(current, goal_state)

    def update_state(self, robot_id: str, new_state: Dict[str, Any], merge: bool = True) -> None:
        """
        Обновить состояние робота.

        :param robot_id: идентификатор робота
        :param new_state: новое состояние (или его часть)
        :param merge: если True, объединяет с существующим состоянием; если False, заменяет полностью
        """
        if merge:
            old = self.agent_states.get(robot_id, {})
            old.update(new_state)
            self.agent_states[robot_id] = old
        else:
            self.agent_states[robot_id] = new_state.copy()

    def get_state(self, robot_id: str) -> Dict[str, Any]:
        """Возвращает текущее сохранённое состояние робота."""
        return self.agent_states.get(robot_id, {}).copy()

    def clear_state(self, robot_id: str) -> None:
        """Удаляет состояние робота из памяти планировщика."""
        if robot_id in self.agent_states:
            del self.agent_states[robot_id]


# Глобальный экземпляр планировщика
planner: Optional[CerebellumPlanner] = None


def init(name: str) -> None:
    """Инициализация навыка и добавление стандартных действий."""
    global planner
    planner = CerebellumPlanner()

    # Стандартные действия для наземных роботов (spot_micro, gladio_bot и др.)
    planner.add_action("sit", {"is_sitting": False, "is_moving": False}, {"is_sitting": True})
    planner.add_action("stand", {"is_sitting": True}, {"is_sitting": False})
    planner.add_action("move_forward", {"is_sitting": False, "is_moving": False}, {"is_moving": True})
    planner.add_action("move_backward", {"is_sitting": False, "is_moving": False}, {"is_moving": True, "direction": "backward"})
    planner.add_action("stop", {"is_moving": True}, {"is_moving": False})
    planner.add_action("turn_left", {"is_moving": False}, {"orientation": "left"})
    planner.add_action("turn_right", {"is_moving": False}, {"orientation": "right"})
    planner.add_action("takeoff", {"is_flying": False}, {"is_flying": True})
    planner.add_action("land", {"is_flying": True}, {"is_flying": False})
    # Атака: требует, чтобы цель была установлена (has_target)
    planner.add_action("attack", {"has_target": True}, {"has_target": False, "is_attacking": True})
    # Действие для перехода в режим ожидания
    planner.add_action("idle", {}, {"is_moving": False, "is_turning": False, "is_attacking": False})

    logger.info("Cerebellum '%s' инициализирован с %d действиями", name, len(planner.actions))


def handle_message(message: str) -> str:
    """Обработка JSON-команд."""
    try:
        data = json.loads(message)
    except json.JSONDecodeError:
        return json.dumps({"error": "Неверный JSON"})

    if planner is None:
        return json.dumps({"error": "Планировщик не инициализирован"})

    command = data.get("command")
    robot_id = data.get("robot_id")

    if command == "plan":
        goal_state = data.get("goal_state", {})
        if not goal_state:
            return json.dumps({"error": "Не указано целевое состояние"})

        current_state = data.get("current_state")
        if robot_id:
            # Если передан current_state, используем его, иначе берём из хранилища
            if current_state is not None:
                plan = planner.plan_for_robot(robot_id, goal_state, current_state=current_state)
            else:
                plan = planner.plan_for_robot(robot_id, goal_state)
        else:
            # Если robot_id нет, используем только переданное состояние
            if current_state is None:
                return json.dumps({"error": "Не указано текущее состояние (current_state) и не указан robot_id"})
            plan = planner.plan(current_state, goal_state)

        return json.dumps({"plan": plan if plan is not None else []})

    elif command == "update_state":
        if not robot_id:
            return json.dumps({"error": "Не указан robot_id"})
        new_state = data.get("state", {})
        if not new_state:
            return json.dumps({"error": "Не указано новое состояние"})
        merge = data.get("merge", True)  # по умолчанию объединяем
        planner.update_state(robot_id, new_state, merge=merge)
        return json.dumps({"status": "ok"})

    elif command == "get_state":
        if not robot_id:
            return json.dumps({"error": "Не указан robot_id"})
        state = planner.get_state(robot_id)
        return json.dumps(state)

    elif command == "clear_state":
        if not robot_id:
            return json.dumps({"error": "Не указан robot_id"})
        planner.clear_state(robot_id)
        return json.dumps({"status": "ok"})

    elif command == "add_action":
        # Команда для динамического добавления действий (расширяемость)
        name = data.get("name")
        pre = data.get("pre", {})
        eff = data.get("eff", {})
        cost = data.get("cost", 1)
        if not name:
            return json.dumps({"error": "Не указано имя действия"})
        try:
            planner.add_action(name, pre, eff, cost)
        except Exception as e:
            return json.dumps({"error": str(e)})
        return json.dumps({"status": "ok", "action": name})

    else:
        return json.dumps({"error": f"Неизвестная команда: {command}"})


def shutdown(name: Optional[str] = None) -> None:
    """Корректное завершение работы."""
    global planner
    planner = None
    logger.info("Cerebellum выгружен")