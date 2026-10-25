#!/bin/bash
echo "=== Проверка окружения ==="
command -v python3 && echo "✅ python3" || echo "❌ python3"
command -v g++ && echo "✅ g++" || echo "❌ g++"
command -v cmake && echo "✅ cmake" || echo "❌ cmake"
python3 -c "import yaml, flask, flask_socketio, requests, dotenv, openai" 2>/dev/null && echo "✅ Python пакеты" || echo "❌ Не хватает пакетов"
echo "Проверьте .env:"
ls -l ~/uorfin_jus/.env 2>/dev/null || echo "❌ .env не найден"