# Используем официальный образ Python
FROM python:3.10-slim

# Устанавливаем зависимости для Poppler (для pdf2image)
RUN apt-get update && apt-get install -y \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Создаем рабочую директорию
WORKDIR /app

# Копируем зависимости
COPY requirements.txt .

# Устанавливаем Python зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем остальные файлы
COPY . .

# Создаем папку для обработанных PDF
RUN mkdir -p /app/processed_pdfs

# Запускаем бота
CMD ["python", "bot.py"]