FROM python:3.11-slim

# Install system dependencies for Pillow and Cairo
RUN apt-get update && apt-get install -y \
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

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
