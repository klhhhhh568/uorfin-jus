import json, time, sys, os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'core'))
from openrouter_adapter import adapter

ADVISORS = {
    "executor": "Ты — Исполнитель. Предлагай быстрые практичные решения.",
    "critic": "Ты — Критик. Находи риски и слабые места.",
    "observer": "Ты — Наблюдатель. Учитывай долгосрочные последствия."
}

def safe_query(prompt, system_prompt, temperature=0.6):
    try:
        resp = adapter.query(prompt, system_prompt=system_prompt, temperature=temperature)
        if not isinstance(resp, str):
            resp = str(resp)
        return resp[:250]
    except Exception as e:
        return f"[Ошибка: {e}]"

def init(name):
    print(f"Совет '{name}' инициализирован")

def handle_message(message):
    try:
        msg = json.loads(message)
    except:
        return "Ошибка: JSON expected"
    command = msg.get("command")
    if command == "convene":
        question = msg.get("question", "")
        context = msg.get("context", "")
        opinions = {}
        for role, sys_prompt in ADVISORS.items():
            prompt = f"{sys_prompt}\nВопрос: {question}\nКонтекст: {context}\nТвоё мнение (один абзац):"
            opinions[role] = safe_query(prompt, system_prompt=sys_prompt, temperature=0.6)
            time.sleep(0.5)
        votes = {"за": 0, "против": 0}
        for role, op in opinions.items():
            if op.startswith("[Ошибка"):
                votes["против"] += 1
                continue
            vote_prompt = f"Предложение: {question}\nМнение: {op}\nГолосуй 'за' или 'против' одним словом:"
            vote = safe_query(vote_prompt, system_prompt="Ты — беспристрастный голосующий.", temperature=0.1).strip().lower()
            if "за" in vote:
                votes["за"] += 1
            else:
                votes["против"] += 1
        verdict = "принято" if votes["за"] > votes["против"] else "отклонено"
        return json.dumps({"opinions": opinions, "votes": votes, "verdict": verdict}, ensure_ascii=False)
    elif command == "veto":
        return "Вето применено."
    return "Неизвестная команда совета"

def convene(question, context=""):
    """Полный созыв с голосованием (используется для кнопки)."""
    payload = json.dumps({"command": "convene", "question": question, "context": context})
    result_json = handle_message(payload)
    return json.loads(result_json)

def convene_light(question, context=""):
    """Только мнения советников (3 запроса), без голосования."""
    opinions = {}
    for role, sys_prompt in ADVISORS.items():
        prompt = f"{sys_prompt}\nВопрос: {question}\nКонтекст: {context}\nТвоё мнение (один абзац):"
        opinions[role] = safe_query(prompt, system_prompt=sys_prompt, temperature=0.6)
        time.sleep(0.5)
    return {"opinions": opinions, "verdict": "принято"}

def shutdown(name=None):
    print("Совет выгружен")