const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const fs = require('fs');
const http = require('http');

let backendProcess = null;
let mainWindow = null;
let backendReady = false;

// ========== ЛОГИРОВАНИЕ ==========
function log(msg) {
    console.log(`[Electron] ${msg}`);
}

// ========== ОПРЕДЕЛЕНИЕ ПУТИ К БЭКЕНДУ ==========
function getBackendPath() {
    if (app.isPackaged) {
        // В собранном приложении: <app>/resources/backend/run_backend
        const backendDir = path.join(process.resourcesPath, 'backend');
        const exe = process.platform === 'win32' ? 'run_backend.exe' : 'run_backend';
        return path.join(backendDir, exe);
    } else {
        // В режиме разработки: <project>/web/dist/run_backend
        const backendDir = path.join(__dirname, '..', 'web', 'dist');
        const exe = process.platform === 'win32' ? 'run_backend.exe' : 'run_backend';
        return path.join(backendDir, exe);
    }
}

// ========== ЗАПУСК БЭКЕНДА ==========
function startBackend() {
    const backendPath = getBackendPath();
    log(`Путь к бэкенду: ${backendPath}`);

    if (!fs.existsSync(backendPath)) {
        log(`❌ Бэкенд НЕ найден по пути: ${backendPath}`);
        return;
    }

    // Проверка прав на исполнение
    try {
        fs.accessSync(backendPath, fs.constants.X_OK);
        log('✅ Бэкенд имеет права на исполнение');
    } catch (err) {
        log(`⚠️ Нет прав на исполнение: ${err.message}`);
        log('Пробуем добавить права...');
        try {
            fs.chmodSync(backendPath, '755');
            log('✅ Права добавлены');
        } catch (chmodErr) {
            log(`❌ Не удалось добавить права: ${chmodErr.message}`);
        }
    }

    log('🚀 Запуск бэкенда...');

    backendProcess = spawn(backendPath, [], {
        stdio: ['ignore', 'pipe', 'pipe'],
        env: { ...process.env, PYTHONUNBUFFERED: '1' }
        // НЕ указываем cwd — PyInstaller использует свою временную папку
    });

    if (!backendProcess.pid) {
        log('❌ Не удалось создать процесс бэкенда');
        return;
    }

    log(`✅ Процесс создан, PID: ${backendProcess.pid}`);

    // === STDOUT ===
    backendProcess.stdout.on('data', (data) => {
        const lines = data.toString().split('\n');
        lines.forEach(line => {
            if (line.trim()) log(`[Backend] ${line.trim()}`);
            if (line.includes('Running on')) {
                log('✅ Сервер ответил, открываем окно');
                onBackendReady();
            }
        });
    });

    // === STDERR ===
    backendProcess.stderr.on('data', (data) => {
        const lines = data.toString().split('\n');
        lines.forEach(line => {
            if (line.trim()) log(`[Backend ERR] ${line.trim()}`);
        });
    });

    // === ЗАВЕРШЕНИЕ ===
    backendProcess.on('error', (err) => {
        log(`❌ Ошибка процесса: ${err.message}`);
    });

    backendProcess.on('close', (code) => {
        log(`⚠️ Бэкенд завершён с кодом ${code}`);
        backendProcess = null;
    });

    // Fallback: если через 15 секунд сервер не отчитался, пробуем проверить вручную
    setTimeout(() => {
        if (!backendReady) {
            log('⏱ Fallback: проверяем порт 5000 напрямую...');
            checkServer(() => onBackendReady());
        }
    }, 15000);
}

// ========== ПРОВЕРКА СЕРВЕРА ЧЕРЕЗ HTTP ==========
function checkServer(callback, attempts = 15, interval = 1000) {
    const req = http.get('http://127.0.0.1:5000', (res) => {
        log(`✅ Сервер доступен (HTTP ${res.statusCode})`);
        callback();
    });

    req.on('error', (err) => {
        if (attempts > 0) {
            log(`⏳ Ожидание сервера... осталось попыток: ${attempts}`);
            setTimeout(() => checkServer(callback, attempts - 1, interval), interval);
        } else {
            log(`❌ Сервер не поднялся: ${err.message}`);
        }
    });

    req.setTimeout(1500, () => {
        req.destroy();
    });
}

// ========== ОТКРЫТИЕ ОКНА ==========
function onBackendReady() {
    if (backendReady) return;
    backendReady = true;
    createWindow();
}

function createWindow() {
    if (mainWindow) return;

    log('🪟 Создание окна...');

    mainWindow = new BrowserWindow({
        width: 1400,
        height: 900,
        title: 'Urfin Jus',
        show: false,
        webPreferences: {
            nodeIntegration: false,
            contextIsolation: true,
            preload: path.join(__dirname, 'preload.js')
        }
    });

    // Открываем DevTools автоматически для отладки
    mainWindow.webContents.openDevTools({ mode: 'detach' });

    mainWindow.loadURL('http://localhost:5000');

    mainWindow.once('ready-to-show', () => {
        mainWindow.show();
        log('✅ Окно показано');
    });

    mainWindow.webContents.on('did-fail-load', (event, code, desc) => {
        log(`❌ Ошибка загрузки URL: ${code} — ${desc}`);
    });

    mainWindow.webContents.on('did-finish-load', () => {
        log('✅ Страница загружена');
    });

    mainWindow.on('closed', () => {
        mainWindow = null;
    });
}

// ========== ЖИЗНЕННЫЙ ЦИКЛ ==========
app.whenReady().then(() => {
    log('Electron готов');
    startBackend();
});

app.on('window-all-closed', () => {
    log('Все окна закрыты, завершаем бэкенд');
    if (backendProcess) {
        backendProcess.kill('SIGTERM');
        setTimeout(() => {
            if (backendProcess) backendProcess.kill('SIGKILL');
        }, 3000);
    }
    if (process.platform !== 'darwin') {
        app.quit();
    }
});

app.on('before-quit', () => {
    if (backendProcess) {
        backendProcess.kill('SIGTERM');
    }
});