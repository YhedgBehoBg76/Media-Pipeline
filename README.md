# Media Pipeline

Система автоматической обработки видео-контента и публикации на различных платформах(YouTube shorts, VK clips).

## 📋 Описание

Media Pipeline — это микросервисная архитектура для:
- Автоматического сбора видео из различных источников (YouTube, файловая система)
- Обработки видео (сегментация, наложение эффектов, конвертация)
- Публикации готового контента на целевые платформы

## 🏗️ Архитектура

```
┌─────────────┐     ┌─────────────┐      ┌─────────────┐
│   Sources   │────▶│  Processors │────▶│  Uploaders  │
│  (Adapters) │     │  (Pipeline) │      │  (Platforms)│
└─────────────┘     └─────────────┘      └─────────────┘
       │                   │                    │
       ▼                   ▼                    ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   YouTube   │     │ Segmenters  │     │ YouTube API │
│ Filesystem  │     │   Steps     │     │ (Shorts)    │
│   Twitch    │     │  Filters    │     │             │
└─────────────┘     └─────────────┘     └─────────────┘
```

### Компоненты

1. **Sources (Источники)** — адаптеры для получения контента
   - `filesystem` — видео берутся из папки на хосте
   - `youtube_channels` — получение видео с YouTube каналов
   - `youtube_search` — поиск видео на YouTube по запросу

2. **Processors (Обработчики)** — пайплайн обработки видео
   - `simple_cut` — обрезка видео в формат 16:9 (или указанный в platforms.yaml)
   - **Важно:** указание не одинаковых `aspect_ratio` у платформ в `platforms.yaml` может вызвать ошибки

3. **Uploaders (Загрузчики)** — публикация на платформы
   - `youtube_shorts` — публикация в формате YouTube Shorts

4. **Worker** — фоновые задачи через Celery

5. **API** — REST интерфейс для управления

## 🚀 Быстрый старт

### Требования

- Docker & Docker Compose
- Python 3.9+
- YouTube API Key (опционально)
- Google OAuth credentials (для YouTube upload)

### Установка

1. **Клонирование репозитория**
```bash
git clone https://github.com/YhedgBehoBg76/highlightsuploader.git
cd Media-Pipeline
```

2. **Настройка переменных окружения**
```bash
cp .env.example .env
# Отредактируйте .env с вашими значениями
```

3. **Запуск сервисов**
```bash
docker-compose up -d
```

4. **Проверка доступности API**
```bash
curl http://localhost:8000/health
```

## 📡 API Endpoints

### Источники (Sources)

#### Получить список поддерживаемых типов источников
```bash
GET /sources/available-types
```

**Ответ:**
```json
{
  "available_types": ["youtube_search", "youtube_channels", "filesystem"]
}
```

#### Получить список всех источников
```bash
GET /sources
```

#### Создать новый источник
```bash
POST /sources
Content-Type: application/json
```

**Тело запроса:**
```json
{
  "type": "filesystem",
  "config": {
    "path": "/media/filesystem_source_video"
  },
  "publishers": [
    "youtube_shorts"
  ],
  "strategy": [
    "simple_cut"
  ],
  "is_active": true
}
```

**Параметры SourceCreate:**

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `type` | string | ✅ | Тип источника: `filesystem` (видео берутся из папки на хосте), `youtube_channels`, `youtube_search` |
| `config` | object | ❌ | Конфигурация источника (зависит от типа) |
| `publishers` | array[string] | ✅ | Список платформ для публикации: `youtube_shorts` |
| `strategy` | array[string] | ❌ | Список обработчиков (по умолчанию: `["simple_cut"]`) |
| `is_active` | boolean | ❌ | Активен ли источник (по умолчанию: `true`) |

**Важно:** сканируются только активные источники (`is_active=True`)

#### Запустить сканирование источника
```bash
POST /sources/{source_id}/scan
```

### Медиа (Media)

#### Получить список медиа элементов
```bash
GET /media
```

#### Получить статус медиа элемента
```bash
GET /media/{media_id}
```

## 🔌 Типы источников и их конфигурация

### 1. Filesystem (`filesystem`)

Сканирование локальной папки с видеофайлами.

**Конфигурация:**
```json
{
  "path": "/media/filesystem_source_video"
}
```

**Параметры config:**

| Параметр | Тип | Обязательный | По умолчанию | Описание |
|----------|-----|--------------|--------------|----------|
| `path` | string | ✅ | - | Путь к папке с видео |
| `recursive` | boolean | ❌ | `false` | Рекурсивный поиск (не реализовано) |

**Структура метаданных:**

Адаптер поддерживает систему метаданных через JSON файлы:

1. **base.meta.json** — базовые метаданные для всей папки
```json
{
  "folder_title": "Губка Боб",
  "description": "Приключения губки боба и его друзей",
  "tags": ["spongebob", "cartoon", "nickelodeon"]
}
```

2. **video.meta.json** — индивидуальные метаданные для конкретного файла
```json
{
  "title": "Помощник",
  "description": "Серия 1",
  "tags": ["season1", "episode1"]
}
```

**Итоговые метаданные** формируются слиянием base + individual:
- `title`: individual.title или `"${base.folder_title} - ${filename}"`
- `description`: конкатенация base + individual
- `tags`: объединение списков без дубликатов

**Пример создания:**
```bash
curl -X POST http://localhost:8000/sources \
  -H "Content-Type: application/json" \
  -d '{
    "type": "filesystem",
    "config": {
      "path": "/media/filesystem_source_video"
    },
    "publishers": ["s3"]
  }'
```

### 2. YouTube Search (`youtube_search`)

Поиск видео на YouTube по запросу.

**Конфигурация:**
```json
{
  "query": "funny cats",
  "license": "creativeCommon",
  "max_results": 10,
  "order": "relevance"
}
```

**Параметры config:**

| Параметр | Тип | Обязательный | По умолчанию | Описание |
|----------|-----|--------------|--------------|----------|
| `query` | string | ✅ | - | Поисковый запрос |
| `license` | string | ❌ | `creativeCommon` | Фильтр лицензии: `any`, `creativeCommon` |
| `max_results` | integer | ❌ | `10` | Максимум результатов (1-50) |
| `order` | string | ❌ | `relevance` | Сортировка: `date`, `rating`, `relevance`, `title`, `viewCount` |

**Пример создания:**
```bash
curl -X POST http://localhost:8000/sources \
  -H "Content-Type: application/json" \
  -d '{
    "type": "youtube_search",
    "config": {
      "query": "cartoon spongebob",
      "license": "creativeCommon",
      "max_results": 20,
      "order": "viewCount"
    },
    "publishers": ["youtube_shorts"],
    "strategy": ["simple_cut"]
  }'
```

### 3. YouTube Channels (`youtube_channels`)

Получение видео с указанных YouTube каналов с поддержкой пагинации.

**Конфигурация:**
```json
{
  "channels": [
    {"channel_id": "UC123456789", "name": "Channel Name 1"},
    {"channel_id": "UC987654321", "name": "Channel Name 2"}
  ],
  "order": "viewCount",
  "max_results": 10,
  "license": "creativeCommon"
}
```

**Параметры config:**

| Параметр | Тип | Обязательный | По умолчанию | Описание |
|----------|-----|--------------|--------------|----------|
| `channels` | array[object] | ✅ | - | Список каналов с `channel_id` и `name` |
| `order` | string | ❌ | `viewCount` | Сортировка: `date`, `rating`, `relevance`, `viewCount` |
| `max_results` | integer | ❌ | `10` | Максимум результатов на канал (1-50) |
| `license` | string | ❌ | `creativeCommon` | Фильтр лицензии: `any`, `creativeCommon` |

**Примечание:** Адаптер автоматически сохраняет состояние пагинации (`current_channel_index`, `last_page_token`) в config источника после каждого сканирования.

**Пример создания:**
```bash
curl -X POST http://localhost:8000/sources \
  -H "Content-Type: application/json" \
  -d '{
    "type": "youtube_channels",
    "config": {
      "channels": [
        {"channel_id": "UCqECaJ8Gagnn7YCbPEzWH6g", "name": "Tom Scott"},
        {"channel_id": "UCHnyfMqiRRG1u-2MsSQLbXA", "name": "Veritasium"}
      ],
      "order": "date",
      "max_results": 5
    },
    "publishers": ["youtube_shorts"]
  }'
```

## 🎯 Стратегии обработки (Strategy)

Стратегия определяет как видео будет обработано перед публикацией. Параметр `strategy` — это список обработчиков (processors), которые применяются к видео последовательно в рамках пайплайна.

**Реализованные обработчики:**
- `simple_cut` — обрезка видео в формат 16:9 (или тот, который указан в `platforms.yaml`). **Важно:** указание не одинаковых `aspect_ratio` у платформ в `platforms.yaml` может вызвать ошибку при нарезке.

**Как работает пайплайн обработки:**

Пайплайн (`ProcessingPipeline`) реализует композитный паттерн — объединяет несколько стратегий обработки в цепочку. Каждый шаг получает результат предыдущего шага и передаёт свой результат следующему.

Пример из кода (`app/modules/processors/pipeline.py`):
```python
pipeline = ProcessingPipeline([
    SimpleCutStep(),
    LightEffectsStep(),
    SubtitlesStep()
])
pipeline.process("input.mp4", "output.mp4", params)
```

**Конфигурация сегментера** задается в `segmenters.yaml`:
```yaml
segmenter: "fixed_duration_segmenter"

fixed_duration_segmenter:
  overlap: 0
  output_dir: "/tmp/media/{media_id}/segments/"
  min_chunk: 5
```

При создании источника вы указываете список стратегий в поле `strategy`. Например:
```json
{
  "strategy": ["simple_cut"]
}
```

В будущем возможно добавление новых обработчиков для расширения функциональности пайплайна.

## 📤 Платформы публикации (Publishers)

**Реализованные публикаторы:**
- `youtube_shorts` — публикация видео в формате YouTube Shorts

Платформы настраиваются в `platforms.yaml`:

### YouTube Shorts
```yaml
youtube_shorts:
  constraints:
    max_duration: 55
    aspect_ratio: "9:16"
    max_file_size_mb: 512
  quotas:
    daily_limit: 6
  upload_defaults:
    privacy: "public"
    category_id: "22"
    title_prefix: "Short"
```

## 🔧 Конфигурация

### Переменные окружения (.env)

```bash
# Database
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=media_pipeline
DATABASE_URL=postgresql://postgres:postgres@db:5432/media_pipeline

# RabbitMQ
RABBITMQ_USER=guest
RABBITMQ_PASSWORD=guest
RABBITMQ_URL=amqp://guest:guest@queue:5672//

# MinIO/S3
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
S3_ENDPOINT=http://storage:9000
S3_BUCKET=media-pipeline

# Security
SECRET_KEY=your-secret-key-here

# YouTube API
YOUTUBE_API_KEY=your-youtube-api-key

# Google OAuth (для YouTube upload)
GOOGLE_CREDENTIALS_PATH=/app/secrets/google_client_secret.json

# Filesystem source
FILESYSTEM_SOURCE_VIDEOS_FOLDER=/path/to/local/videos
```

### Файлы конфигурации

- `platforms.yaml` — настройки платформ публикации
- `segmenters.yaml` — настройки сегментеров видео

## 🧪 Тестирование

```bash
# Запуск тестов
pytest tests/

# E2E тест пайплайна
pytest tests/test_e2e_pipeline.py

# Тест процессоров
pytest tests/test_processors.py

# Тест сегментеров
pytest tests/test_segmenter.py
```

## 📦 Структура проекта

```
/workspace
├── app/
│   ├── api/
│   │   └── routes/
│   │       ├── sources.py      # API endpoints для источников
│   │       └── media.py        # API endpoints для медиа
│   ├── core/
│   │   ├── config.py           # Настройки приложения
│   │   ├── database.py         # Подключение к БД
│   │   └── types.py            # Кастомные типы
│   ├── models/
│   │   ├── sources.py          # Модель Source
│   │   ├── media.py            # Модель MediaItem
│   │   └── publication.py      # Модель Publication
│   ├── modules/
│   │   ├── sources/            # Адаптеры источников
│   │   │   ├── base.py         # Базовый класс SourceAdapter
│   │   │   ├── youtube.py      # YouTube адаптеры
│   │   │   ├── filesystem.py   # Filesystem адаптер
│   │   │   └── adapter_factory.py # Фабрика адаптеров
│   │   ├── processors/         # Обработчики видео
│   │   ├── downloaders/        # Загрузчики видео
│   │   └── uploaders/          # Загрузчики на платформы
│   ├── schemas/
│   │   ├── source.py           # Pydantic схемы для Source
│   │   └── media.py            # Pydantic схемы для Media
│   └── worker/
│       └── tasks.py            # Celery задачи
├── migrations/                  # Миграции БД
├── scripts/                     # Скрипты утилит
├── tests/                       # Тесты
├── platforms.yaml               # Конфиг платформ
├── segmenters.yaml              # Конфиг сегментеров
└── docker-compose.yml           # Docker композиция
```

## 🔄 Рабочий процесс

1. **Создание источника**
   ```bash
   POST /sources
   ```

2. **Сканирование источника**
   ```bash
   POST /sources/{source_id}/scan
   ```
   - Адаптер получает список новых видео
   - Создаются записи MediaItem со статусом `PENDING`

3. **Обработка (Worker)**
   - Celery worker забирает задачи из очереди
   - Скачивание видео → Сегментация → Обработка → Загрузка

4. **Публикация**
   - Готовые сегменты публикуются на указанные платформы
   - Статус обновляется в БД

## ⚠️ Важные замечания

### При создании источника:

1. **Config должен соответствовать типу источника**
   - `youtube_search` требует `query`
   - `youtube_channels` требует `channels` массив
   - `filesystem` требует `path`

2. **Валидация config**
   - Перед созданием источника можно проверить доступные типы: `GET /sources/available-types`
   - Адаптер проверяет валидность config при сканировании

3. **State management**
   - Некоторые адаптеры (например, `youtube_channels`) обновляют `config` источника в процессе работы
   - Сохраняется состояние пагинации для продолжения с места остановки

4. **Publishers и Strategy**
   - `publishers` определяет куда будет загружен контент
   - `strategy` определяет как видео будет обработано

## 🛠️ Разработка

```bash
# Установка зависимостей
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Запуск API локально
uvicorn app.main:app --reload

# Запуск worker
celery -A app.worker.tasks:celery_app worker --loglevel=info

# Запуск beat (планировщик)
celery -A app.worker.tasks beat --loglevel=info
```

## 📝 Лицензия

MIT
