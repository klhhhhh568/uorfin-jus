#include <iostream>
#include <string>
#include <cstring>
#include <map>
#include <sys/socket.h>
#include <netinet/in.h>
#include <unistd.h>
#include <signal.h>
#include <Python.h>
#include "nlohmann/json.hpp"

using json = nlohmann::json;
#define PORT 5555

std::map<std::string, PyObject*> loaded_py_modules;

std::string call_python_method(PyObject* module, const std::string& method_name,
                               const std::string& arg = "") {
    PyObject* func = PyObject_GetAttrString(module, method_name.c_str());
    if (!func || !PyCallable_Check(func)) {
        Py_XDECREF(func);
        return "Ошибка: метод '" + method_name + "' не найден";
    }
    PyObject* pArg = PyUnicode_FromString(arg.c_str());
    PyObject* pResult = nullptr;
    try {
        pResult = PyObject_CallFunctionObjArgs(func, pArg, NULL);
    } catch (...) {
        // перехват C++ исключений (маловероятно, но для безопасности)
        Py_XDECREF(pArg);
        Py_DECREF(func);
        return "Ошибка: исключение C++ при вызове Python";
    }
    Py_DECREF(pArg);
    Py_DECREF(func);
    if (pResult && PyUnicode_Check(pResult)) {
        std::string result = PyUnicode_AsUTF8(pResult);
        Py_DECREF(pResult);
        return result;
    } else {
        if (pResult) Py_DECREF(pResult);
        PyErr_Print();  // выведет traceback в stderr
        return "Ошибка: метод '" + method_name + "' не вернул строку";
    }
}

std::string load_python_plugin(const std::string& plugin_name) {
    if (!Py_IsInitialized()) {
        Py_Initialize();
        PyObject* sys_path = PySys_GetObject("path");
        PyList_Append(sys_path, PyUnicode_FromString("skills"));
    }
    PyObject* pName = PyUnicode_DecodeFSDefault(plugin_name.c_str());
    PyObject* pModule = PyImport_Import(pName);
    Py_DECREF(pName);
    if (!pModule) {
        PyErr_Print();
        return "Ошибка: не удалось импортировать модуль '" + plugin_name + "'";
    }
    call_python_method(pModule, "init", plugin_name);
    loaded_py_modules[plugin_name] = pModule;
    return "Python-плагин '" + plugin_name + "' успешно загружен";
}

std::string process_message(const std::string& raw) {
    json msg;
    try {
        msg = json::parse(raw);
    } catch (...) {
        json err;
        err["text"] = "Ошибка: неверный JSON";
        return err.dump();
    }

    if (msg.contains("command") && msg["command"] == "load_py") {
        std::string plugin = msg["plugin"];
        std::string result = load_python_plugin(plugin);
        json resp;
        resp["text"] = result;
        return resp.dump();
    }

    if (msg.contains("skill")) {
        std::string skill = msg["skill"];
        if (loaded_py_modules.find(skill) != loaded_py_modules.end()) {
            std::string text = msg.value("text", "");
            std::string answer;
            try {
                answer = call_python_method(loaded_py_modules[skill], "handle_message", text);
            } catch (const std::exception& e) {
                answer = std::string("Ошибка Python: ") + e.what();
            }
            json resp;
            resp["text"] = answer;
            return resp.dump();
        } else {
            json err;
            err["text"] = "Ошибка: плагин '" + skill + "' не загружен";
            return err.dump();
        }
    }

    // эхо
    json echo;
    echo["text"] = "Эхо: " + raw;
    return echo.dump();
}

int server_fd;
volatile sig_atomic_t running = 1;

void signal_handler(int sig) { running = 0; }

int main() {
    signal(SIGINT, signal_handler);
    signal(SIGTERM, signal_handler);
    struct sockaddr_in address;
    int opt = 1;
    socklen_t addrlen = sizeof(address);
    const int buf_size = 1024 * 256; // 256 КБ
    char* buffer = new char[buf_size];

    server_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (server_fd < 0) { std::cerr << "Ошибка сокета"; return 1; }
    setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
    address.sin_family = AF_INET;
    address.sin_addr.s_addr = INADDR_ANY;
    address.sin_port = htons(PORT);
    if (bind(server_fd, (struct sockaddr*)&address, sizeof(address)) < 0) {
        std::cerr << "Ошибка bind"; close(server_fd); return 1;
    }
    if (listen(server_fd, 3) < 0) {
        std::cerr << "Ошибка listen"; close(server_fd); return 1;
    }
    std::cout << "Урфин Джус (ядро + Python) на порту " << PORT << std::endl;
    std::cout << "Ожидание соединений..." << std::endl;

    while (running) {
        int client = accept(server_fd, (struct sockaddr*)&address, &addrlen);
        if (client < 0) {
            if (errno == EINTR && !running) break;
            std::cerr << "accept error: " << strerror(errno) << std::endl;
            continue;
        }
        std::cout << "Клиент подключился" << std::endl;
        memset(buffer, 0, buf_size);
        ssize_t bytes = recv(client, buffer, buf_size-1, 0);
        if (bytes > 0) {
            buffer[bytes] = '\0';
            std::string request(buffer);
            std::cout << "Получено: " << request << std::endl;

            std::string response = process_message(request);
            send(client, response.c_str(), response.length(), 0);
            std::cout << "Отправлено: " << response << std::endl;
        }
        close(client);
    }

    // Выгрузка плагинов
    for (auto& pair : loaded_py_modules) {
        call_python_method(pair.second, "shutdown");
        Py_DECREF(pair.second);
    }
    if (Py_IsInitialized()) Py_Finalize();
    delete[] buffer;
    close(server_fd);
    return 0;
}