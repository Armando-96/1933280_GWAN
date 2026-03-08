import json
import time
import os
import pika
import psycopg2
import requests

# Environment variables (passed via docker-compose)
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
DB_HOST = os.getenv("DB_HOST", "postgres-db")
DB_NAME = os.getenv("DB_NAME", "mars_db")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")
SIMULATOR_URL = os.getenv("SIMULATOR_URL", "http://simulator:8080")
QUEUE_NAME = os.getenv("QUEUE_NAME", "normalized_telemetry")

def connect_db():
    """Connect to PostgreSQL with a retry mechanism in case it's not ready yet."""
    while True:
        try:
            conn = psycopg2.connect(
                host=DB_HOST,
                database=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD
            )
            print("Successfully connected to PostgreSQL!")
            return conn
        except psycopg2.OperationalError:
            print("Waiting for PostgreSQL database to be ready...")
            time.sleep(3)

def evaluate_rule(sensor_value, operator, threshold):
    """Evaluate the rule condition."""
    try:
        # Cast to float to safely compare numeric values
        val = float(sensor_value)
        thresh = float(threshold)
        
        if operator == '>': return val > thresh
        if operator == '>=': return val >= thresh
        if operator == '<': return val < thresh
        if operator == '<=': return val <= thresh
        if operator == '=': return val == thresh
    except ValueError:
        print(f"[WARNING] Could not cast values to float (sensor: {sensor_value}, threshold: {threshold})")
        # Fallback to string comparison if casting fails
        if operator == '=': return str(sensor_value) == str(threshold)
    
    return False

def trigger_actuator(actuator_name, on_off_value):
    """Send a REST POST request to the simulator to change the actuator state."""
    
    # Map the integer from the DB (0 or 1) to the string required by the API ("OFF" or "ON")
    target_state = "ON" if on_off_value == 1 else "OFF"
    
    url = f"{SIMULATOR_URL}/api/actuators/{actuator_name}"
    payload = {"state": target_state}
    headers = {'Content-Type': 'application/json'}
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code in[200, 201, 202, 204]:
            print(f"[ACTUATOR TRIGGERED] {actuator_name} set to {target_state}! (Status: {response.status_code})")
        else:
            print(f"[ACTUATOR ERROR] Failed to set {actuator_name}. Status: {response.status_code}, Response: {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"[CONNECTION ERROR] Cannot reach the simulator at {url}: {e}")

def process_message(ch, method, properties, body, db_conn):
    """Callback triggered every time a message is received from RabbitMQ."""
    try:
        # Decode the incoming JSON payload
        event = json.loads(body)
        sensor_id = event.get("sensor_id")
        current_value = event.get("value")
        
        print(f"Received data: {sensor_id} = {current_value} {event.get('unit', '')}")

        # Query the database to find rules associated with this sensor
        cursor = db_conn.cursor()
        query = """
            SELECT operator, value, actuator_name, On_off 
            FROM rules 
            WHERE sensor_name = %s
        """
        cursor.execute(query, (sensor_id,))
        rules = cursor.fetchall()
        
        # Check every rule found for this sensor
        for rule in rules:
            operator, threshold, actuator_name, on_off_value = rule
            
            # If the condition is met, trigger the actuator
            if evaluate_rule(current_value, operator, threshold):
                state_str = "ON" if on_off_value == 1 else "OFF"
                print(f"[RULE MATCH] Condition met: {sensor_id} ({current_value}) {operator} {threshold} -> Action: Set {actuator_name} to {state_str}")
                trigger_actuator(actuator_name, on_off_value)

        cursor.close()
        
        # Acknowledge the message so RabbitMQ removes it from the queue
        ch.basic_ack(delivery_tag=method.delivery_tag)

    except Exception as e:
        print(f"Error processing message: {e}")
        # Optionally, you can Negative-Acknowledge (NACK) to requeue the message
        # ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

def main():
    # 1. Connect to Database
    db_conn = connect_db()

    # 2. Connect to RabbitMQ (with retry mechanism)
    while True:
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
            channel = connection.channel()
            # Declare the queue (creates it if it doesn't exist)
            channel.queue_declare(queue=QUEUE_NAME, durable=True)
            print(f"Successfully connected to RabbitMQ! Listening on queue '{QUEUE_NAME}'...")
            break
        except pika.exceptions.AMQPConnectionError:
            print("Waiting for RabbitMQ broker to be ready...")
            time.sleep(3)

    # Wrap the callback to pass the DB connection
    on_message_callback = lambda ch, method, properties, body: process_message(ch, method, properties, body, db_conn)

    # 3. Start consuming messages
    channel.basic_qos(prefetch_count=1) # Process one message at a time
    channel.basic_consume(queue=QUEUE_NAME, on_message_callback=on_message_callback)
    
    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        print("Stopping Automation Engine...")
        channel.stop_consuming()
    finally:
        if connection.is_open:
            connection.close()
        if db_conn:
            db_conn.close()

if __name__ == '__main__':
    main()