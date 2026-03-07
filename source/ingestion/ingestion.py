import os
import time
import json
import pika
import requests
from datetime import datetime, timezone

# Configurazioni tramite variabili d'ambiente
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "admin")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "admin")
EXCHANGE_NAME = "mars_events"
SIMULATOR_BASE_URL = os.getenv("SIMULATOR_URL", "http://simulator:8080")


def connect_to_broker(max_retries=10, delay=5):
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
    raise Exception("Impossibile connettersi a RabbitMQ.")


def normalize_rest_payload(raw_data):
    """
    Analizza il JSON in ingresso, capisce a quale schema appartiene
    ed emette una lista di eventi unificati.
    """
    events = []

    # Base comune per tutti gli eventi unificati
    base_event = {
        "sensor_id": raw_data.get("sensor_id"),
        "timestamp": raw_data.get("captured_at", datetime.now(timezone.utc).isoformat()),
        "status": raw_data.get("status", "ok"),
        "source_protocol": "REST"
    }

    # 1. rest.chemistry.v1 (ha un array 'measurements')
    if "measurements" in raw_data:
        for meas in raw_data["measurements"]:
            event = base_event.copy()
            event.update({
                "metric": meas.get("metric"),
                "value": meas.get("value"),
                "unit": meas.get("unit")
            })
            events.append(event)

    # 2. rest.particulate.v1 (ha pm1, pm25 e pm10 come campi diretti)
    elif "pm25_ug_m3" in raw_data:
        for pm_type in ["pm1", "pm25", "pm10"]:
            key = f"{pm_type}_ug_m3"
            if key in raw_data:
                event = base_event.copy()
                event.update({
                    "metric": pm_type,
                    "value": raw_data.get(key),
                    "unit": "ug/m3"
                })
                events.append(event)

    # 3. rest.level.v1 (ha level_pct e level_liters)
    elif "level_pct" in raw_data:
        for metric, unit in [("level_pct", "%"), ("level_liters", "L")]:
            if metric in raw_data:
                event = base_event.copy()
                event.update({
                    "metric": metric,
                    "value": raw_data.get(metric),
                    "unit": unit
                })
                events.append(event)

    # 4. rest.scalar.v1 (caso base: una sola metrica, un solo valore)
    else:
        event = base_event.copy()
        event.update({
            "metric": raw_data.get("metric"),
            "value": raw_data.get("value"),
            "unit": raw_data.get("unit")
        })
        events.append(event)

    return events


def poll_and_publish(channel):
    # Tutti i sensori REST indicati nella traccia
    sensors_to_poll = [
        "greenhouse_temperature",
        "entrance_humidity",
        "co2_hall",
        "hydroponic_ph",
        "water_tank_level",
        "corridor_pressure",
        "air_quality_pm25",
        "air_quality_voc"
    ]

    for sensor_id in sensors_to_poll:
        try:
            response = requests.get(f"{SIMULATOR_BASE_URL}/api/sensors/{sensor_id}", timeout=3)

            if response.status_code == 200:
                raw_data = response.json()

                # Questa funzione ora restituisce una lista di eventi
                unified_events = normalize_rest_payload(raw_data)

                # Pubblichiamo ogni evento separatamente
                for unified_event in unified_events:
                    channel.basic_publish(
                        exchange=EXCHANGE_NAME,
                        routing_key='',
                        body=json.dumps(unified_event),
                        properties=pika.BasicProperties(
                            content_type='application/json',
                            delivery_mode=2
                        )
                    )
                print(f"[x] Inviati {len(unified_events)} eventi per: {sensor_id}")
            else:
                print(f"[!] Errore HTTP {response.status_code} dal sensore {sensor_id}")

        except requests.exceptions.RequestException as e:
            print(f"[!] Errore connessione al simulatore per {sensor_id}: {e}")


def main():
    connection = connect_to_broker()
    channel = connection.channel()
    channel.exchange_declare(exchange=EXCHANGE_NAME, exchange_type='fanout')
    print(f"Exchange '{EXCHANGE_NAME}' pronto. Inizio ingestione REST...")

    try:
        while True:
            poll_and_publish(channel)
            time.sleep(5)  # Polling ogni 5 secondi
    except KeyboardInterrupt:
        print("\nArresto del servizio...")
    finally:
        if connection and not connection.is_closed:
            connection.close()


if __name__ == "__main__":
    main()