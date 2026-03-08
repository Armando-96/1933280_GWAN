import os
import json
import asyncio
from datetime import datetime, timezone
from time import sleep

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import aio_pika
import httpx
from rules_manager import send_delete_rule, send_insert_rule, receive_rules_events

from fastapi.staticfiles import StaticFiles

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "admin")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "admin")
EXCHANGE_NAME = "mars_events"
SIMULATOR_URL = os.getenv("SIMULATOR_URL", "http://simulator:8080")

app = FastAPI()

# Pydantic model for actuator control
from pydantic import BaseModel
class ActuatorStateRequest(BaseModel):
    state: str  # "ON" or "OFF"

# app.mount("/", ... removed from here to fix WS conflict
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

@app.post("/actuators/{name}")
async def proxy_actuator_control(name: str, req: ActuatorStateRequest):
    """
    Agisce come proxy per inviare comandi al simulatore.
    """
    async with httpx.AsyncClient() as client:
        try:
            url = f"{SIMULATOR_URL}/api/actuators/{name}"
            response = await client.post(url, json={"state": req.state}, timeout=5)
            if response.status_code == 200:
                print(f"[x] Comando inviato con successo a {name}: {req.state}")
                return response.json()
            else:
                return {"error": f"Simulatore ha risposto con {response.status_code}", "detail": response.text}
        except Exception as e:
            return {"error": "Impossibile contattare il simulatore", "detail": str(e)}

# Montiamo la cartella static DOPO aver definito le altre rotte
# altrimenti FastAPI intercetta la richiesta WebSocket e pensa sia una richiesta HTTP statica.
app.mount("/", StaticFiles(directory="static", html=True), name="static")

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

async def poll_actuators():
    """
    Interroga il simulatore ogni 5 secondi per ottenere lo stato degli attuatori.
    Formatta i dati come eventi unificati e li trasmette via WebSocket.
    """
    # Attendiamo che il simulatore sia potenzialmente pronto
    await asyncio.sleep(5)
    
    async with httpx.AsyncClient(base_url=SIMULATOR_URL) as client:
        while True:
            try:
                response = await client.get("/api/actuators", timeout=3)
                if response.status_code == 200:
                    data = response.json()
                    # data format: {"actuators": {"actuator_name": "ON/OFF", ...}}
                    actuators = data.get("actuators", {})
                    
                    for name, state in actuators.items():
                        event = {
                            "sensor_id": name,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "metric": "state",
                            "value": state,
                            "unit": "",
                            "status": "ok",
                            "source_protocol": "ACTUATORS"
                        }
                        await manager.broadcast(json.dumps(event))
                    
                    print(f"[x] Dashboard: Aggiornati lo stato di {len(actuators)} attuatori")
                else:
                    print(f"[!] Dashboard: Errore polling attuatori: {response.status_code}")
            except Exception as e:
                print(f"[!] Dashboard: Eccezione polling attuatori: {e}")
            
            await asyncio.sleep(5)

@app.on_event("startup")
async def startup_event():
    # Questo task in background leggerà di continuo da RabbitMQ e manderà alla Dashboard
    asyncio.create_task(consume_rabbitmq())
    # Questo task interroga direttamente il simulatore per gli attuatori
    asyncio.create_task(poll_actuators())

    # ESEMPI DI CHIAMATE rules_manager.py
    # await send_delete_rule(55)
    # await send_insert_rule("sensore_11", "<", 55.0, "attuatore_2", 1)

