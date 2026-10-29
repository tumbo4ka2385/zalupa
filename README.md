# LM Studio → Docker Code Agent

Мини-агент, который соединяет локальную нейросеть из **LM Studio** с **Docker Desktop**:
модель получает задачу, пишет код, код выполняется в изолированном контейнере,
результат возвращается модели, и так по кругу — пока задача не будет решена.

```
┌─────────────┐   OpenAI-compatible    ┌──────────────┐   docker exec   ┌───────────────┐
│  LM Studio  │ ◄────────────────────► │  agent.py    │ ◄─────────────► │  sandbox      │
│  (localhost │      /v1/chat/...      │  (Python)    │   файлы в       │  контейнер    │
│   :1234)    │                        │              │   /workspace    │  (Linux)      │
└─────────────┘                        └──────────────┘                 └───────────────┘
```

## Что умеет

- Подключается к LM Studio по стандартному OpenAI-совместимому API (`http://localhost:1234/v1`).
- Автоматически поднимает Docker-контейнер `lmstudio-sandbox`.
- Парсит код из ответов модели (`python и `bash блоки).
- Поддерживает **именование файлов**: первая строка блока — `# file: app.py`.
- Запускает код внутри контейнера, забирает stdout/stderr/exit code.
- Отдаёт результат обратно модели для следующего шага.
- Останавливается, когда модель пишет `TASK_COMPLETE` или достигнут лимит шагов.
- Интерактивный чат-режим и режим «руками полазить в контейнере».

## Требования

1. **Docker Desktop** запущен.
2. **LM Studio** запущен с включённым локальным сервером:

- `Developer` → `Local Server` → `Start Server`
- Адрес по умолчанию: `http://localhost:1234`
- Загружена любая модель (Qwen2.5-Coder, DeepSeek-Coder, Llama-3.1 и т.п.)
3. **Python 3.10+** на хосте.

## Установка

```
git clone <этот-проект>   # или просто распакуйте архив
cd lmstudio-docker-agent

python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env       # при необходимости отредактируйте
```

## Быстрый старт

```
# 1. Проверить, что LM Studio отвечает и показать список моделей
python main.py models

# 2. Собрать образ песочницы (один раз)
python main.py build

# 3. Запустить одну задачу
python main.py run "Напиши на Python скрипт, который считает первые 20 чисел Фибоначчи и сохраняет их в fib.txt"

# 4. Интерактивный режим (несколько задач подряд, контейнер живёт между ними)
python main.py chat

# 5. Залезть руками внутрь контейнера
python main.py shell

# 6. Удалить контейнер и очистить рабочую папку
python main.py reset
```

## Как это работает

1. `main.py` читает конфиг из `.env`.
2. `LMStudioClient` — тонкая обёртка над `openai.OpenAI(base_url=...)`.
3. `DockerExecutor` — поднимает контейнер `python:3.12-slim` (или ваш кастомный образ),
монтирует временную папку хоста в `/workspace`, умеет запускать bash и python.
4. `CodeAgent` — цикл:

- отправляет задачу + историю в LM Studio,
- вырезает из ответа fenced code blocks,
- сохраняет каждый блок в файл в `/workspace`,
- выполняет его,
- добавляет stdout/stderr/exit code в историю как `user`-сообщение,
- повторяет, пока не `TASK_COMPLETE` или лимит шагов.

### Формат, которого придерживается модель

```
Сейчас создам файл и запущу его.

```python
# file: hello.py
print("Hello from Docker!")
```

Затем проверю результат.
```

Правила задаются в `SYSTEM_PROMPT` в файле `agent.py` — их можно свободно менять.

## Файлы проекта

| Файл ↕▾ | Назначение ↕▾ |
|---|---|
| −`main.py` | CLI: `models`, `build`, `run`, `chat`, `shell`, `reset` |
| −`config.py` | Загрузка настроек из `.env` |
| `lmstudio_client.py` | Клиент LM Studio (OpenAI-compatible) |
| `docker_executor.py` | Управление контейнером и выполнение кода |
| `agent.py` | Основной цикл «модель → код → запуск → результат» |
| `docker/sandbox.Dockerfile` | Образ песочницы с numpy/pandas/requests |
| `.env.example` | Шаблон конфигурации |
| `examples/tasks.txt` | Примеры задач, которые можно сразу запустить |
⚙

## Кастомный образ песочницы

По умолчанию используется `python:3.12-slim` — он скачается автоматически.
Если хочется, чтобы внутри уже были `numpy`, `pandas`, `requests`, `git`, `curl`:

```
python main.py build       # соберёт docker/sandbox.Dockerfile в образ lmstudio-sandbox:latest
```

Затем в `.env`:

```
DOCKER_IMAGE=lmstudio-sandbox:latest
```

## Конфигурация (`.env`)

| Переменная | По умолчанию | Описание |
|---|---|---|
| `LM_STUDIO_BASE_URL` | `http://localhost:1234/v1` | Адрес API LM Studio |
| `LM_STUDIO_API_KEY` | `lm-studio` | LM Studio не проверяет, но openai-клиент требует непустое |
| `LM_STUDIO_MODEL` | (авто) | Имя модели; если пусто — берётся первая доступная |
| `TEMPERATURE` | `0.2` | Для кода лучше низкая |
| `MAX_TOKENS` | `2048` | Максимум токенов на ответ |
| `DOCKER_IMAGE` | `python:3.12-slim` | Образ песочницы |
| `CONTAINER_NAME` | `lmstudio-sandbox` | Имя контейнера |
| `CONTAINER_WORKSPACE` | `/workspace` | Рабочая папка внутри контейнера |
| `MAX_STEPS` | `25` | Лимит итераций агента на одну задачу |
| `EXEC_TIMEOUT` | `180` | Таймаут одной команды, секунды |

## Безопасность

- Контейнер **не пробрасывает порты** и **не монтирует** ваш проект — только временную папку.
- По умолчанию нет `--network host`; сеть внутри контейнера доступна, но наружу порты не открыты.
- Модель может выполнять произвольный код. Не давайте агенту секретов и не используйте его
на продовой машине без понимания рисков. Если нужно совсем жёстко — добавьте `--network none`
в `docker_executor.py` (тогда `pip install` внутри работать не будет).

## Частые проблемы

- **`Cannot connect to the Docker daemon`** — Docker Desktop не запущен.
- **`Connection refused` к LM Studio** — сервер не запущен (`Developer → Local Server → Start`).
- **Модель отвечает без кода** — увеличить `MAX_TOKENS`, снизить температуру,
либо взять модель, заточенную под код (Qwen2.5-Coder-7B/14B — хороший выбор).
- **Долго** — ограничьте `MAX_STEPS` и `EXEC_TIMEOUT`, и используйте модель поменьше.
- **`pip install` исчезает после перезапуска** — установки живут только в текущем контейнере.
Хотите постоянство — соберите свой образ через `python main.py build`.