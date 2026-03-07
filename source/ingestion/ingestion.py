import os
import time
import json
import pika
import requests
import threading
import websocket
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
    Analizza il JSON REST in ingresso ed emette una lista di eventi unificati.
    """
    events = []
    base_event = {
        "sensor_id": raw_data.get("sensor_id"),
        "timestamp": raw_data.get("captured_at", datetime.now(timezone.utc).isoformat()),
        "status": raw_data.get("status", "ok"),
        "source_protocol": "REST"
    }

    if "measurements" in raw_data:
        for meas in raw_data["measurements"]:
            event = base_event.copy()
            event.update({"metric": meas.get("metric"), "value": meas.get("value"), "unit": meas.get("unit")})
            events.append(event)
    elif "pm25_ug_m3" in raw_data:
        for pm_type in ["pm1", "pm25", "pm10"]:
            key = f"{pm_type}_ug_m3"
            if key in raw_data:
                event = base_event.copy()
                event.update({"metric": pm_type, "value": raw_data.get(key), "unit": "ug/m3"})
                events.append(event)
    elif "level_pct" in raw_data:
        for metric, unit in [("level_pct", "%"), ("level_liters", "L")]:
            if metric in raw_data:
                event = base_event.copy()
                event.update({"metric": metric, "value": raw_data.get(metric), "unit": unit})
                events.append(event)
    else:
        event = base_event.copy()
        event.update({"metric": raw_data.get("metric"), "value": raw_data.get("value"), "unit": raw_data.get("unit")})
        events.append(event)

    return events


def normalize_telemetry_payload(raw_data):
    """
    Analizza il JSON Telemetria (Pub/Sub) in ingresso ed emette una lista di eventi unificati.
    """
    events = []
    topic = raw_data.get("topic", "")
    base_topic_name = topic.split("/")[-1]  # Es. 'mars/telemetry/solar_array' -> 'solar_array'

    base_event = {
        "timestamp": raw_data.get("event_time", datetime.now(timezone.utc).isoformat()),
        "status": raw_data.get("status", "ok"),
        "source_protocol": "TELEMETRY"
    }

    # 1. Schema topic.power.v1
    if "power_kw" in raw_data:
        subsystem = raw_data.get("subsystem", "unknown")
        sensor_id = f"{base_topic_name}_{subsystem}"
        metrics = [
            ("power", raw_data.get("power_kw"), "kW"),
            ("voltage", raw_data.get("voltage_v"), "V"),
            ("current", raw_data.get("current_a"), "A"),
            ("cumulative_energy", raw_data.get("cumulative_kwh"), "kWh")
        ]
        for metric, value, unit in metrics:
            if value is not None:
                ev = base_event.copy()
                ev.update({"sensor_id": sensor_id, "metric": metric, "value": value, "unit": unit})
                events.append(ev)

    # 2. Schema topic.environment.v1
    elif "measurements" in raw_data:
        source = raw_data.get("source", {})
        sensor_id = f"{base_topic_name}_{source.get('system', 'sys')}_{source.get('segment', 'seg')}"
        for meas in raw_data.get("measurements", []):
            ev = base_event.copy()
            ev.update({"sensor_id": sensor_id, "metric": meas.get("metric"), "value": meas.get("value"),
                       "unit": meas.get("unit")})
            events.append(ev)

    # 3. Schema topic.thermal_loop.v1
    elif "temperature_c" in raw_data:
        sensor_id = f"{base_topic_name}_{raw_data.get('loop', 'unknown')}"
        metrics = [("temperature", raw_data.get("temperature_c"), "°C"), ("flow", raw_data.get("flow_l_min"), "L/min")]
        for metric, value, unit in metrics:
            if value is not None:
                ev = base_event.copy()
                ev.update({"sensor_id": sensor_id, "metric": metric, "value": value, "unit": unit})
                events.append(ev)

    # 4. Schema topic.airlock.v1
    elif "cycles_per_hour" in raw_data:
        sensor_id = f"{base_topic_name}_{raw_data.get('airlock_id', 'unknown')}"
        metrics = [("cycles", raw_data.get("cycles_per_hour"), "cycles/h"),
                   ("state", raw_data.get("last_state"), "state")]
        for metric, value, unit in metrics:
            if value is not None:
                ev = base_event.copy()
                ev.update({"sensor_id": sensor_id, "metric": metric, "value": value, "unit": unit})
                events.append(ev)

    return events


def telemetry_worker(topic):
    """
    Funzione eseguita in un thread separato. Si connette via WebSocket a un topic,
    normalizza i dati e li invia a RabbitMQ.
    """
    # IMPORTANTE: Pika non è thread-safe, quindi ogni thread deve avere la sua connessione
    connection = connect_to_broker()
    channel = connection.channel()
    channel.exchange_declare(exchange=EXCHANGE_NAME, exchange_type='fanout')

    ws_url = SIMULATOR_BASE_URL.replace("http://", "ws://") + f"/api/telemetry/ws?topic={topic}"

    def on_message(ws, message):
        try:
            raw_data = json.loads(message)
            unified_events = normalize_telemetry_payload(raw_data)

            for unified_event in unified_events:
                channel.basic_publish(
                    exchange=EXCHANGE_NAME,
                    routing_key='',
                    body=json.dumps(unified_event),
                    properties=pika.BasicProperties(content_type='application/json', delivery_mode=2)
                )
            print(f"[x] Inviati {len(unified_events)} eventi TELEMETRY per: {topic}")
        except Exception as e:
            print(f"[!] Errore elaborazione telemetria {topic}: {e}")

    def on_error(ws, error):
        print(f"[!] WebSocket Errore su {topic}: {error}")

    def on_close(ws, close_status_code, close_msg):
        print(f"[-] WebSocket disconnesso da {topic}")

    def on_open(ws):
        print(f"[+] WebSocket connesso con successo a {topic}")

    # Avvia la connessione WebSocket in ascolto continuo
    ws = websocket.WebSocketApp(ws_url, on_open=on_open, on_message=on_message, on_error=on_error, on_close=on_close)

    # run_forever blocca il thread e ascolta. reconnect=5 fa in modo che se la rete cade, riprova dopo 5 secondi.
    ws.run_forever(reconnect=5)


def poll_and_publish(channel):
    sensors_to_poll = [
        "greenhouse_temperature", "entrance_humidity", "co2_hall", "hydroponic_ph",
        "water_tank_level", "corridor_pressure", "air_quality_pm25", "air_quality_voc"
    ]
    for sensor_id in sensors_to_poll:
        try:
            response = requests.get(f"{SIMULATOR_BASE_URL}/api/sensors/{sensor_id}", timeout=3)
            if response.status_code == 200:
                raw_data = response.json()
                unified_events = normalize_rest_payload(raw_data)
                for unified_event in unified_events:
                    channel.basic_publish(
                        exchange=EXCHANGE_NAME, routing_key='', body=json.dumps(unified_event),
                        properties=pika.BasicProperties(content_type='application/json', delivery_mode=2)
                    )
                print(f"[x] Inviati {len(unified_events)} eventi REST per: {sensor_id}")
            else:
                print(f"[!] Errore HTTP {response.status_code} dal sensore {sensor_id}")
        except requests.exceptions.RequestException as e:
            print(f"[!] Errore connessione al simulatore per {sensor_id}: {e}")


def main():
    # 1. Avvia i worker in background per le telemetrie via WebSocket
    telemetry_topics = [
        "mars/telemetry/solar_array",
        "mars/telemetry/radiation",
        "mars/telemetry/life_support",
        "mars/telemetry/thermal_loop",
        "mars/telemetry/power_bus",
        "mars/telemetry/power_consumption",
        "mars/telemetry/airlock"
    ]

    print("Avvio dei thread per l'ascolto delle telemetrie...")
    for topic in telemetry_topics:
        t = threading.Thread(target=telemetry_worker, args=(topic,), daemon=True)
        t.start()
        time.sleep(0.5)  # Pausa leggera per non intasare RabbitMQ con 7 connessioni simultanee

    # 2. Nel thread principale, continua con l'ingestione REST
    connection = connect_to_broker()
    channel = connection.channel()
    channel.exchange_declare(exchange=EXCHANGE_NAME, exchange_type='fanout')
    print(f"Exchange '{EXCHANGE_NAME}' pronto. Inizio ingestione REST principale...")

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