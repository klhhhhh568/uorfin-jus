#!/bin/bash
cd "$(dirname "$0")"
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1

# 1. Принудительно убиваем старый процесс ядра, если он завис
echo "🔍 Проверяю старый процесс ядра..."
if pgrep -x "uorfin_core" > /dev/null; then
    echo "⚠ Старый процесс uorfin_core найден, убиваю..."
    pkill -9 uorfin_core
    sleep 1
fi

# 2. Ждём освобождения порта 5555
echo "🔍 Проверяю порт 5555..."
while ss -tuln | grep -q 5555; do
    echo "Порт 5555 занят, жду..."
    sleep 1
done

# 3. Запускаем ядро в фоне
./core/build/uorfin_core &
CORE_PID=$!
echo "Ядро запущено (PID $CORE_PID)"

# Даём ядру секунду на инициализацию
sleep 1

# 4. Активируем виртуальное окружение и запускаем веб-сервер
source ~/uorfin_env/bin/activate
python3 web/web_server.py