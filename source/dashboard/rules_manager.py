import os
import json
import asyncio
import aio_pika

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "admin")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "admin")
EXCHANGE_NAME = "rules_management"

async def get_connection():
    """
    Crea e restituisce una connessione a RabbitMQ.
    """
    return await aio_pika.connect_robust(
        f"amqp://{RABBITMQ_USER}:{RABBITMQ_PASS}@{RABBITMQ_HOST}/"
    )

async def publish_message(message_dict: dict):
    """
    Pubblica un dizionario come JSON sull'exchange 'rules_management'.
    """
    connection = await get_connection()
    async with connection:
        channel = await connection.channel()
        exchange = await channel.declare_exchange(EXCHANGE_NAME, aio_pika.ExchangeType.FANOUT)
        
        message = aio_pika.Message(
            body=json.dumps(message_dict).encode(),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT
        )
        await exchange.publish(message, routing_key="")

async def send_delete_rule(rule_id: int):
    """
    Invia un evento per eliminare una regola.
    JSON inviato: {"rule_id": <integer>}
    """
    event = {"rule_id": rule_id}
    await publish_message(event)

async def send_insert_rule(sensor_name: str, operator: str, value: float, actuator_name: str, on_off: int):
    """
    Invia un evento per inserire una nuova regola.
    JSON inviato: {"sensor_name": <string>, "operator": <string>, "value": <numeric>, "actuator_name": <string>, "On_off": <integer>}
    """
    event = {
        "sensor_name": sensor_name,
        "operator": operator,
        "value": float(value),
        "actuator_name": actuator_name,
        "On_off": int(on_off)
    }
    await publish_message(event)

async def receive_rules_events():
    """
    Ascolta i messaggi sull'exchange 'rules_management'.
    Quando riceve un evento con la chiave 'rules', restituisce l'array delle regole come una lista di dizionari JSON.
    JSON atteso per l'elaborazione: {"rules": [ <rule1>, <rule2>, ..., <rulen> ]}
    """
    while True:
        try:
            connection = await get_connection()
            async with connection:
                channel = await connection.channel()
                exchange = await channel.declare_exchange(EXCHANGE_NAME, aio_pika.ExchangeType.FANOUT)
                
                # Coda temporanea esclusiva per ricevere l'elenco delle regole broadcasted
                queue = await channel.declare_queue(exclusive=True)
                await queue.bind(exchange)
                
                async with queue.iterator() as queue_iter:
                    async for message in queue_iter:
                        async with message.process():
                            payload = json.loads(message.body.decode())
                            
                            # Verifica se il messaggio contiene "rules"
                            if "rules" in payload:
                                return payload["rules"]
        except Exception as e:
            print(f"Errore nella ricezione messaggi da rules_management: {e}")
            await asyncio.sleep(5)
