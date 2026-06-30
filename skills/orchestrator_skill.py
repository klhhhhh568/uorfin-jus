import os, json, yaml, logging, re, sys
from pathlib import Path
from dotenv import load_dotenv

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from core.openrouter_adapter import adapter as llm_adapter
from core_client import send_to_core
import memory_skill

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    fh = logging.FileHandler('/tmp/orchestrator_skill.log', encoding='utf-8')
    fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(fh)

config_dir = os.getenv("UORFIN_CONFIG_DIR", os.path.expanduser("~/uorfin_jus"))
dotenv_path = os.path.join(config_dir, ".env")
if Path(dotenv_path).exists():
    load_dotenv(dotenv_path)

MODEL_NAME = os.getenv("OPENROUTER_MODEL", "poolside/laguna-xs.2:free")
RULES = None

def load_charter():
    global RULES
    if RULES is None:
        charter_path = os.path.join(os.path.dirname(__file__), "..", "uorfin_charter.yaml")
        with open(charter_path, "r", encoding="utf-8") as f:
            RULES = yaml.safe_load(f)
    return RULES

def build_system_prompt():
    charter = load_charter()
    tools = charter.get("tools", {})
    tools_desc = json.dumps(tools, ensure_ascii=False, indent=2)
    base_prompt = charter.get("system_prompt", "")
    return base_prompt + f"\n\nДоступные инструменты:\n{tools_desc}"

def call_tool(tool_name, params):
    resp = send_to_core({"skill": tool_name, "text": json.dumps(params)})
    return resp.get("text", str(resp))

def extract_json(text):
    if RULES is None:
        return None
    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if match:
        text = match.group(1).strip()
    else:
        text = text.strip()
    if not (text.startswith('{') and text.endswith('}')):
        return None
    try:
        parsed = json.loads(text)
        if "tool" in parsed and parsed["tool"] in RULES.get("tools", {}):
            return parsed
    except:
        pass
    return None

def init(name):
    logger.info(f"Оркестратор '{name}' инициализируется")
    if llm_adapter is None or not llm_adapter.configured:
        raise RuntimeError("OpenRouter не настроен")
    load_charter()
    logger.info("Оркестратор готов")

def process_message(user_input: str, context: dict = None) -> str:
    user_text = user_input
    try:
        data = json.loads(user_input)
        if isinstance(data, dict) and 'user_message' in data:
            user_text = data['user_message']
    except:
        pass

    if not user_text.strip():
        return "Пустой запрос."

    if llm_adapter is None or not llm_adapter.configured:
        return "Оркестратор не настроен."

    # Получаем историю диалога
    history = memory_skill.get_context()
    if history:
        prompt = f"История диалога:\n{history}\n\nНовый запрос: {user_text}"
    else:
        prompt = user_text

    system_prompt = build_system_prompt()
    try:
        response = llm_adapter.query(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=0.2
        )
        if response.startswith("Ошибка LLM:"):
            logger.error(f"Ошибка LLM: {response}")
            return "Сервис временно недоступен. Попробуйте позже."

        content = response.strip()

        # === ОЧИСТКА ОТ АРТЕФАКТОВ ===
        clean_marker = "Чтобы вызвать инструмент"
        if clean_marker in content:
            content = content[:content.rfind(clean_marker)].strip()
        content = re.sub(r'^`C`\s*$', '', content, flags=re.MULTILINE).strip()
        content = '\n'.join(line for line in content.splitlines() if line.strip())
        content = content.encode('utf-8', 'replace').decode('utf-8')
        # ============================

        logger.debug(f"Ответ модели (после очистки): {content[:300]}")

        tool_json = extract_json(content)
        if tool_json:
            tool_name = tool_json.get("tool")
            tool_params = tool_json.get("params", {})
            logger.info(f"Вызов инструмента: {tool_name}")
            tool_result = call_tool(tool_name, tool_params)
            final_prompt = f"Инструмент {tool_name} вернул: {tool_result}\nПользователь: {user_text}\nОтветь кратко."
            final_response = llm_adapter.query(
                prompt=final_prompt,
                system_prompt=system_prompt,
                temperature=0.5
            )
            if final_response.startswith("Ошибка LLM:"):
                logger.error(f"Ошибка LLM при финальном ответе: {final_response}")
                return "Инструмент выполнен, но ответить не могу. Попробуйте позже."
            final_text = final_response.strip()
            memory_skill.add_message("assistant", final_text)
            return final_text

        memory_skill.add_message("assistant", content)
        return content
    except Exception as e:
        logger.exception("Ошибка оркестратора")
        return f"Внутренняя ошибка: {str(e)}"

handle_message = process_message