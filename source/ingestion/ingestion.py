import os
import time
import json
import pika
import requests
from datetime import datetime, timezone

# Configurazioni tramite variabili d'ambiente (comode per Docker)
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "admin")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "admin")
EXCHANGE_NAME = "mars_events"

# URL base del simulatore (dipende dal nome del container nel docker-compose)
SIMULATOR_BASE_URL = os.getenv("SIMULATOR_URL", "http://simulator:8080")


def connect_to_broker(max_retries=10, delay=5):
    """Connessione a RabbitMQ con retry (necessario per docker-compose)."""
    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
    parameters = pika.ConnectionParameters(host=RABBITMQ_HOST, credentials=credentials)

    for attempt in range(max_retries):
        try:
            print(f"Tentativo connessione a RabbitMQ ({attempt + 1}/{max_retries})...")
            connection = pika.BlockingConnection(parameters)
            print("Connessione a RabbitMQ stabilita!")
            return connection
        except pika.exceptions.AMQPConnectionError:
            print(f"RabbitMQ non ancora pronto, riprovo in {delay} secondi...")
            time.sleep(delay)
    raise Exception("Impossibile connettersi a RabbitMQ. Ingestione fallita.")


def normalize_rest_scalar(raw_data):
    """
    Converte il payload 'rest.scalar.v1' nello schema di evento unificato.
    """
    return {
        "sensor_id": raw_data.get("sensor_id"),
        "timestamp": raw_data.get("captured_at", datetime.now(timezone.utc).isoformat()),
        "metric": raw_data.get("metric"),
        "value": raw_data.get("value"),
        "unit": raw_data.get("unit"),
        "status": raw_data.get("status", "ok"),
        "source_protocol": "REST"
    }


def poll_and_publish(channel):
    """
    Recupera i dati dai sensori REST, li normalizza e li pubblica.
    Nota: Verifica l'endpoint esatto tramite la documentazione OpenAPI (http://localhost:8080/docs).
    """
    # Lista di esempio dei sensori REST da interrogare
    sensors_to_poll = ["greenhouse_temperature", "entrance_humidity", "co2_hall", "hydroponic_ph", "water_tank_level", "corridor_pressure", "air_quality_pm25", "air_quality_voc"]

    for sensor_id in sensors_to_poll:
        try:
            # Effettua il polling (sostituisci l'URL con quello esatto descritto nelle OpenAPI se diverso)
            response = requests.get(f"{SIMULATOR_BASE_URL}/api/sensors/{sensor_id}", timeout=3)

            if response.status_code == 200:
                raw_data = response.json()

                # Normalizza i dati
                unified_event = normalize_rest_scalar(raw_data)

                # Pubblica su RabbitMQ
                channel.basic_publish(
                    exchange=EXCHANGE_NAME,
                    routing_key='',  # Ignorata nei fanout exchange
                    body=json.dumps(unified_event),
                    properties=pika.BasicProperties(
                        content_type='application/json',
                        delivery_mode=2  # Messaggio persistente
                    )
                )
                print(f"[x] Inviato evento normalizzato per: {sensor_id}")
            else:
                print(f"[!] Errore HTTP {response.status_code} dal sensore {sensor_id}")

        except requests.exceptions.RequestException as e:
            print(f"[!] Errore di connessione al simulatore per {sensor_id}: {e}")


def main():
    # 1. Connessione e auto-configurazione di RabbitMQ
    connection = connect_to_broker()
    channel = connection.channel()
    channel.exchange_declare(exchange=EXCHANGE_NAME, exchange_type='fanout')
    print(f"Exchange '{EXCHANGE_NAME}' pronto.")

    # 2. Loop continuo di ingestione
    try:
        while True:
            print("\n--- Inizio ciclo di polling ---")
            poll_and_publish(channel)
            # Attende 5 secondi prima del prossimo polling
            time.sleep(5)
    except KeyboardInterrupt:
        print("Arresto del servizio di ingestione...")
    finally:
        if connection and not connection.is_closed:
            connection.close()


if __name__ == "__main__":
    main()