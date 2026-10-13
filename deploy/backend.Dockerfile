FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
WORKDIR /app/backend
COPY backend/requirements*.txt ./
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch==2.9.1 torchvision==0.24.1 && pip install -r requirements.txt
COPY backend/ ./
RUN useradd -m -u 10001 logistics && mkdir -p /app/storage && chown -R logistics:logistics /app
USER logistics
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--ws-max-size", "2097152", "--ws-max-queue", "1"]
