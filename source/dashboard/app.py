import os
import json
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import aio_pika

from fastapi.staticfiles import StaticFiles

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "admin")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "admin")
EXCHANGE_NAME = "mars_events"

app = FastAPI()

# Montiamo la cartella static alla radice '/' per servire index.html 
# e qualsiasi altro file (CSS, JS) che aggiungeremo in futuro.
app.mount("/", StaticFiles(directory="static", html=True), name="static")

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except RuntimeError:
                pass

manager = ConnectionManager()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

async def consume_rabbitmq():
    # Aspettiamo qualche secondo per assicurarci che RabbitMQ sia pronto al boot
    await asyncio.sleep(5)
    
    while True:
        try:
            print(f"Tentativo connessione a RabbitMQ ({RABBITMQ_HOST})...")
            connection = await aio_pika.connect_robust(
                f"amqp://{RABBITMQ_USER}:{RABBITMQ_PASS}@{RABBITMQ_HOST}/"
            )
            async with connection:
                print("Connesso a RabbitMQ! In attesa di messaggi...")
                channel = await connection.channel()
                
                # Ci colleghiamo all'Exchange che usa ingestion
                exchange = await channel.declare_exchange(EXCHANGE_NAME, aio_pika.ExchangeType.FANOUT)
                
                # Creiamo una coda esclusiva invisibile: serve solo per ricevere questa copia di eventi
                queue = await channel.declare_queue(exclusive=True)
                await queue.bind(exchange)
                
                async with queue.iterator() as queue_iter:
                    async for message in queue_iter:
                        async with message.process():
                            payload = message.body.decode()
                            # Spariamo subito il messaggio normalizzato al Frontend HTML!
                            await manager.broadcast(payload)
                            
        except Exception as e:
            print(f"Errore connessione a RabbitMQ, riprovo tra 5s: {e}")
            await asyncio.sleep(5)

@app.on_event("startup")
async def startup_event():
    # Questo task in background leggerà di continuo da RabbitMQ e manderà alla Dashboard
    asyncio.create_task(consume_rabbitmq())
