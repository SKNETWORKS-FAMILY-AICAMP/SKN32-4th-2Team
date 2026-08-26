# LLM/Dockerfile
FROM python:3.11-slim
LABEL authors="4nchez"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8002

CMD ["python", "-m", "app.main"]