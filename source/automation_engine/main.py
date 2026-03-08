import json
import time
import os
import threading
import pika
import psycopg2
import requests
import aio_pika
import asyncio

# Variabili d'ambiente
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "admin")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "admin")
DB_HOST = os.getenv("DB_HOST", "db")
DB_NAME = os.getenv("DB_NAME", "mars")
DB_USER = os.getenv("DB_USER", "admin")
DB_PASSWORD = os.getenv("DB_PASSWORD", "password")
SIMULATOR_URL = os.getenv("SIMULATOR_URL", "http://simulator:8080")
QUEUE_NAME = os.getenv("QUEUE_NAME", "normalized_telemetry")

EXCHANGE_NAME = "rules_management"

# ──────────────────────────────────────────────
# DATABASE
# ──────────────────────────────────────────────

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


def db_insert_rule(conn, sensor_name, operator, value, actuator_name, on_off):
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO rules (sensor_name, operator, value, actuator_name, On_off) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (sensor_name, operator, float(value), actuator_name, int(on_off))
            )
            new_id = cur.fetchone()[0]
            conn.commit()
            print(f"✅ [RULES MGR] Inserted rule id={new_id}: IF {sensor_name} {operator} {value} THEN {actuator_name} {'ON' if on_off else 'OFF'}")
            return new_id
    except Exception as e:
        conn.rollback()
        print(f"❌ [RULES MGR] Failed to insert rule: {e}")
        return None


def db_delete_rule(conn, rule_id):
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM rules WHERE id = %s", (rule_id,))
            conn.commit()
            print(f"🗑️ [RULES MGR] Deleted rule id={rule_id}")
    except Exception as e:
        conn.rollback()
        print(f"❌ [RULES MGR] Failed to delete rule id={rule_id}: {e}")


def db_fetch_all_rules(conn):
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, sensor_name, operator, value, actuator_name, On_off FROM rules")
            rows = cur.fetchall()
            return [
                {
                    "id": r[0],
                    "sensor_name": r[1],
                    "operator": r[2],
                    "value": float(r[3]),
                    "actuator_name": r[4],
                    "On_off": r[5]
                }
                for r in rows
            ]
    except Exception as e:
        print(f"❌ [RULES MGR] Failed to fetch rules: {e}")
        return []


# ──────────────────────────────────────────────
# AUTOMATION LOGIC
# ──────────────────────────────────────────────

def evaluate_rule(sensor_value, operator, threshold):
    try:
        val = float(sensor_value)
        thresh = float(threshold)
        if operator == '>':  return val > thresh
        if operator == '>=': return val >= thresh
        if operator == '<':  return val < thresh
        if operator == '<=': return val <= thresh
        if operator == '=':  return val == thresh
    except ValueError:
        if operator == '=': return str(sensor_value) == str(threshold)
    return False


def trigger_actuator(actuator_name, on_off_value):
    target_state = "ON" if on_off_value == 1 else "OFF"
    url = f"{SIMULATOR_URL}/api/actuators/{actuator_name}"
    try:
        response = requests.post(url, json={"state": target_state},
                                 headers={'Content-Type': 'application/json'})
        if response.status_code in [200, 201, 202, 204]:
            print(f"🚀 [ACTUATOR TRIGGERED] {actuator_name} set to {target_state}! (Status: {response.status_code})")
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
                print(f"🔥 [RULE MATCH] {sensor_id} ({current_value}) {operator} {threshold} -> Set {actuator_name} to {state_str}")
                trigger_actuator(actuator_name, on_off_value)

        cursor.close()
        ch.basic_ack(delivery_tag=method.delivery_tag)

    except Exception as e:
        print(f"❌ Error processing message: {e}")


# ──────────────────────────────────────────────
# RULES MANAGEMENT LISTENER  (async, separate thread)
# ──────────────────────────────────────────────

async def rules_management_listener(db_conn):
    """
    Listens on the 'rules_management' fanout exchange.

    Handles three kinds of messages published by rules_manager.py:

      1. Insert rule:
         {"sensor_name": str, "operator": str, "value": float,
          "actuator_name": str, "On_off": int}

      2. Delete rule:
         {"rule_id": int}

      3. List-rules request  (dashboard asks for current rules):
         {"action": "get_rules"}
         → automation engine replies by publishing {"rules": [...]} back
           on the same exchange so the dashboard can pick it up.
    """
    amqp_url = f"amqp://{RABBITMQ_USER}:{RABBITMQ_PASS}@{RABBITMQ_HOST}/"

    while True:
        try:
            connection = await aio_pika.connect_robust(amqp_url)
            async with connection:
                channel = await connection.channel()
                exchange = await channel.declare_exchange(
                    EXCHANGE_NAME, aio_pika.ExchangeType.FANOUT, durable=True
                )

                # Exclusive, auto-delete queue — one per engine instance
                queue = await channel.declare_queue(exclusive=True)
                await queue.bind(exchange)

                print(f"✅ [RULES MGR] Listening on exchange '{EXCHANGE_NAME}'...")

                async with queue.iterator() as queue_iter:
                    async for message in queue_iter:
                        async with message.process():
                            await _handle_rules_event(message.body, db_conn, exchange)

        except Exception as e:
            print(f"⚠️ [RULES MGR] Connection error: {e}. Reconnecting in 5 s...")
            await asyncio.sleep(5)


async def _handle_rules_event(raw_body: bytes, db_conn, exchange):
    try:
        payload = json.loads(raw_body.decode())
    except json.JSONDecodeError as e:
        print(f"❌ [RULES MGR] Invalid JSON: {e}")
        return

    # ── DELETE rule ──────────────────────────────
    if "rule_id" in payload and len(payload) == 1:
        rule_id = payload["rule_id"]
        db_delete_rule(db_conn, rule_id)
        return

    # ── GET rules (dashboard requesting full list) ──
    if payload.get("action") == "get_rules":
        rules = db_fetch_all_rules(db_conn)
        response = aio_pika.Message(
            body=json.dumps({"rules": rules}).encode(),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT
        )
        await exchange.publish(response, routing_key="")
        print(f"📤 [RULES MGR] Published rules list ({len(rules)} rules) to exchange.")
        return

    # ── INSERT rule ──────────────────────────────
    required = {"sensor_name", "operator", "value", "actuator_name", "On_off"}
    if required.issubset(payload.keys()):
        db_insert_rule(
            db_conn,
            payload["sensor_name"],
            payload["operator"],
            payload["value"],
            payload["actuator_name"],
            payload["On_off"]
        )
        return

    print(f"⚠️ [RULES MGR] Unrecognised message, ignoring: {payload}")
    
async def rules_broadcast_loop(db_conn):
    amqp_url = f"amqp://{RABBITMQ_USER}:{RABBITMQ_PASS}@{RABBITMQ_HOST}/"
    while True:
        try:
            connection = await aio_pika.connect_robust(amqp_url)
            async with connection:
                channel = await connection.channel()
                exchange = await channel.declare_exchange(
                    EXCHANGE_NAME, aio_pika.ExchangeType.FANOUT, durable=True
                )
                while True:
                    rules = db_fetch_all_rules(db_conn)
                    await exchange.publish(
                        aio_pika.Message(
                            body=json.dumps({"rules": rules}).encode(),
                            delivery_mode=aio_pika.DeliveryMode.PERSISTENT
                        ),
                        routing_key=""
                    )
                    print(f"📤 [RULES MGR] Broadcast {len(rules)} rules.")
                    await asyncio.sleep(5)
        except Exception as e:
            print(f"⚠️ [RULES MGR] Broadcast error: {e}. Retry in 5s...")
            await asyncio.sleep(5)


def start_rules_listener_thread(db_conn):
    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.create_task(rules_management_listener(db_conn))
        loop.create_task(rules_broadcast_loop(db_conn))
        loop.run_forever()

    t = threading.Thread(target=_run, daemon=True, name="rules-mgr-listener")
    t.start()
    print("🧵 [RULES MGR] Listener thread started.")


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────

def main():
    db_conn = connect_db()

    # Start rules-management listener in background
    start_rules_listener_thread(db_conn)

    # Connect to RabbitMQ for telemetry consumption
    while True:
        try:
            credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
            parameters = pika.ConnectionParameters(host=RABBITMQ_HOST, credentials=credentials)
            connection = pika.BlockingConnection(parameters)
            channel = connection.channel()

            channel.queue_declare(queue=QUEUE_NAME, durable=True)
            channel.queue_bind(exchange='mars_events', queue=QUEUE_NAME, routing_key='#')

            print(f"✅ Connesso a RabbitMQ! Coda '{QUEUE_NAME}' collegata all'Exchange...")
            break
        except pika.exceptions.AMQPConnectionError as e:
            print(f"⏳ Waiting for RabbitMQ broker... Error: {e}")
            time.sleep(3)

    on_message_callback = lambda ch, method, properties, body: \
        process_message(ch, method, properties, body, db_conn)

    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=QUEUE_NAME, on_message_callback=on_message_callback)

    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        channel.stop_consuming()
    finally:
        if connection.is_open:
            connection.close()
        if db_conn:
            db_conn.close()


if __name__ == '__main__':
    main()