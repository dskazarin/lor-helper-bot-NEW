FROM python:3.11-slim

WORKDIR /app

# Установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Создание папок для данных
RUN mkdir -p /app/data /app/backups /app/logs && \
    chmod 777 /app/data /app/backups /app/logs

# Копирование кода
COPY bot.py .

# Запуск бота
CMD ["python", "bot.py"]
