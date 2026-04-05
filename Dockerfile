FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    gcc \
    libcairo2-dev \
    pkg-config \
    libfreetype6-dev \
    libjpeg-dev \
    libpng-dev \
    fonts-dejavu-core \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
COPY fonts/ /app/fonts/

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
