FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiamo i file Python necessari per il backend
COPY app.py .
COPY rules_manager.py .

# Copiamo la cartella con i file del frontend (HTML/CSS/JS)
COPY static ./static

ENV PYTHONUNBUFFERED=1
ENV RABBITMQ_HOST=rabbitmq
ENV RABBITMQ_USER=admin
ENV RABBITMQ_PASS=admin

# Esponiamo la porta 8000 per la dashboard HTML
EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
