FROM python:3.11

WORKDIR /app

COPY test.py .

CMD ["python", "test.py"]
