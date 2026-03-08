import json
import time
import os
import pika
import psycopg2
import requests

# Variabili d'ambiente
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "admin")  # <-- ORA USA ADMIN
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "admin")  # <-- ORA USA ADMIN
DB_HOST = os.getenv("DB_HOST", "db")
DB_NAME = os.getenv("DB_NAME", "mars")
DB_USER = os.getenv("DB_USER", "admin")
DB_PASSWORD = os.getenv("DB_PASSWORD", "password")
SIMULATOR_URL = os.getenv("SIMULATOR_URL", "http://simulator:8080")
QUEUE_NAME = os.getenv("QUEUE_NAME", "normalized_telemetry")

def connect_db():
    while True:
        try:
            conn = psycopg2.connect(
                host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASSWORD
            )
            print("✅ Successfully connected to PostgreSQL!")
            return conn
        except psycopg2.OperationalError:
            print("⏳ Waiting for PostgreSQL database to be ready...")
            time.sleep(3)

def evaluate_rule(sensor_value, operator, threshold):
    try:
        val = float(sensor_value)
        thresh = float(threshold)
        if operator == '>': return val > thresh
        if operator == '>=': return val >= thresh
        if operator == '<': return val < thresh
        if operator == '<=': return val <= thresh
        if operator == '=': return val == thresh
    except ValueError:
        if operator == '=': return str(sensor_value) == str(threshold)
    return False

def trigger_actuator(actuator_name, on_off_value):
    target_state = "ON" if on_off_value == 1 else "OFF"
    url = f"{SIMULATOR_URL}/api/actuators/{actuator_name}"
    payload = {"state": target_state}
    headers = {'Content-Type': 'application/json'}
    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code in[200, 201, 202, 204]:
            print(f"🚀[ACTUATOR TRIGGERED] {actuator_name} set to {target_state}! (Status: {response.status_code})")
        else:
            print(f"⚠️ [ACTUATOR ERROR] Failed to set {actuator_name}. Status: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"❌ [CONNECTION ERROR] Cannot reach the simulator: {e}")

def process_message(ch, method, properties, body, db_conn):
    try:
        event = json.loads(body)
        sensor_id = event.get("sensor_id")
        current_value = event.get("value")
        
        print(f"📥 Received data: {sensor_id} = {current_value} {event.get('unit', '')}")

        cursor = db_conn.cursor()
        query = "SELECT operator, value, actuator_name, On_off FROM rules WHERE sensor_name = %s"
        cursor.execute(query, (sensor_id,))
        rules = cursor.fetchall()
        
        for rule in rules:
            operator, threshold, actuator_name, on_off_value = rule
            if evaluate_rule(current_value, operator, threshold):
                state_str = "ON" if on_off_value == 1 else "OFF"
                print(f"🔥[RULE MATCH] {sensor_id} ({current_value}) {operator} {threshold} -> Set {actuator_name} to {state_str}")
                trigger_actuator(actuator_name, on_off_value)

        cursor.close()
        ch.basic_ack(delivery_tag=method.delivery_tag)

    except Exception as e:
        print(f"❌ Error processing message: {e}")

def main():
    db_conn = connect_db()

    # CONNESSIONE A RABBITMQ CON CREDENZIALI FORZATE E BINDING
    while True:
        try:
            credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
            parameters = pika.ConnectionParameters(
                host=RABBITMQ_HOST, 
                credentials=credentials
            )
            connection = pika.BlockingConnection(parameters)
            channel = connection.channel()
            
            # 1. Dichiara la tua coda fissa (come prima)
            channel.queue_declare(queue=QUEUE_NAME, durable=True)
            
            # ---> 2. AGGIUNGI QUESTA RIGA: Collega la tua coda all'Exchange! <---
            # Sostituisci 'NOME_DEL_TUO_EXCHANGE' con quello che hai trovato al Passo 1.
            # Se la Routing Key nel passo 1 era vuota o diversa, metti '#' (che significa "ascolta tutto")
            channel.queue_bind(exchange='mars_events', queue=QUEUE_NAME, routing_key='#')
            
            print(f"✅ Connesso a RabbitMQ! Coda '{QUEUE_NAME}' collegata all'Exchange...")
            break
        except pika.exceptions.AMQPConnectionError as e:
            print(f"⏳ Waiting for RabbitMQ broker... Error: {e}")
            time.sleep(3)
            
    on_message_callback = lambda ch, method, properties, body: process_message(ch, method, properties, body, db_conn)

    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=QUEUE_NAME, on_message_callback=on_message_callback)
    
    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        channel.stop_consuming()
    finally:
        if connection.is_open: connection.close()
        if db_conn: db_conn.close()

if __name__ == '__main__':
    main()