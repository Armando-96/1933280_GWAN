# Usa un'immagine Python leggera ufficiale
FROM python:3.10-slim

# Imposta la cartella di lavoro all'interno del container
WORKDIR /app

# Copia il file delle dipendenze e installale
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia il codice sorgente
COPY ingestion.py .

# Imposta le variabili d'ambiente di default
ENV PYTHONUNBUFFERED=1
ENV RABBITMQ_HOST=rabbitmq
ENV RABBITMQ_USER=admin
ENV RABBITMQ_PASS=admin
ENV SIMULATOR_URL=http://simulator:8080

# Comando per avviare il servizio
CMD ["python", "ingestion.py"]