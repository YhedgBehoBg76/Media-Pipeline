# Базовый образ Python (версия 3.11)
FROM python:3.11-slim

# Рабочая директория внутри контейнера
WORKDIR /app

# Переменные окружения для оптимизации Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 1. Установка системных зависимостей
# ffmpeg — критически важен для обработки видео!
# build-essential и libpq-dev нужны для компиляции некоторых Python-пакетов
RUN apt-get update && apt-get install -y \
    ffmpeg \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 2. Копируем только файл зависимостей сначала
# Это позволяет Docker закэшировать слой и не переустанавливать пакеты при каждом изменении кода
COPY requirements.txt .

# 3. Устанавливаем Python-пакеты
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# 4. Копируем весь исходный код проекта
COPY . .

# 5. Команда по умолчанию (будет переопределена в docker-compose)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]