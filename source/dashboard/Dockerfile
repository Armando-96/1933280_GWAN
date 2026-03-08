FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

ENV PYTHONUNBUFFERED=1
ENV RABBITMQ_HOST=rabbitmq
ENV RABBITMQ_USER=admin
ENV RABBITMQ_PASS=admin

# Esponiamo la porta 8000 per la dashboard HTML
EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
