import os
import json
import asyncio
from datetime import datetime, timezone
from pydantic import BaseModel

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import aio_pika
import httpx
from rules_manager import send_delete_rule, send_insert_rule, receive_rules_stream, receive_rules_events

from fastapi.staticfiles import StaticFiles

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "admin")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "admin")
EXCHANGE_NAME = "mars_events"
SIMULATOR_URL = os.getenv("SIMULATOR_URL", "http://simulator:8080")

app = FastAPI()

# Pydantic models
class ActuatorStateRequest(BaseModel):
    state: str  # "ON" or "OFF"

class RuleRequest(BaseModel):
    sensor_name: str
    operator: str
    value: float
    actuator_name: str
    on_off: int # 1 for ON, 0 for OFF

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

@app.post("/rules")
async def create_rule(req: RuleRequest):
    try:
        await send_insert_rule(req.sensor_name, req.operator, req.value, req.actuator_name, req.on_off)
        return {"status": "Rule deployment request sent"}
    except Exception as e:
        return {"error": str(e)}

@app.delete("/rules/{rule_id}")
async def delete_rule(rule_id: int):
    try:
        await send_delete_rule(rule_id)
        return {"status": "Rule deletion request sent"}
    except Exception as e:
        return {"error": str(e)}

# Montiamo la cartella static DOPO aver definito le altre rotte
# altrimenti FastAPI intercetta la richiesta WebSocket e pensa sia una richiesta HTTP statica.
app.mount("/", StaticFiles(directory="static", html=True), name="static")

async def consume_rules_events():
    """
    Ascolta gli eventi dall'exchange rules_management in streaming e li trasmette alla dashboard.
    """
    while True:
        try:
            async for data in receive_rules_stream():
                if data == "online" or data == "offline":
                    event = {"type": "broker_status", "source": "rules", "status": data}
                else:
                    event = {"type": "rules_update", "rules": data}
                await manager.broadcast(json.dumps(event))
        except Exception as e:
            print(f"Errore consume_rules_events: {e}")
            await manager.broadcast(json.dumps({"type": "broker_status", "source": "rules", "status": "offline"}))
            await asyncio.sleep(5)

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
                await manager.broadcast(json.dumps({"type": "broker_status", "source": "sensors", "status": "online"}))
                channel = await connection.channel()
                
                exchange = await channel.declare_exchange(EXCHANGE_NAME, aio_pika.ExchangeType.FANOUT, durable=False)
                queue = await channel.declare_queue(exclusive=True)
                await queue.bind(exchange)
                
                async with queue.iterator() as queue_iter:
                    async for message in queue_iter:
                        async with message.process():
                            try:
                                data = json.loads(message.body.decode())
                                if "source_protocol" not in data:
                                    data["source_protocol"] = "TELEMETRY"
                                await manager.broadcast(json.dumps(data))
                            except Exception as e:
                                print(f"Errore broadcast messaggio RabbitMQ: {e}")
                            
        except Exception as e:
            print(f"Errore connessione a RabbitMQ (sensors), riprovo tra 5s: {e}")
            await manager.broadcast(json.dumps({"type": "broker_status", "source": "sensors", "status": "offline"}))
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

async def poll_rules_periodically():
    """
    Interroga periodicamente receive_rules_events() ogni 5 secondi
    per ottenere l'elenco aggiornato delle regole e trasmetterlo alla dashboard.
    """
    while True:
        try:
            rules = await receive_rules_events()
            if rules is not None:
                await manager.broadcast(json.dumps({"type": "rules_update", "rules": rules}))
        except Exception as e:
            print(f"Errore poll_rules_periodically: {e}")
        await asyncio.sleep(5)

@app.on_event("startup")
async def startup_event():
    # Questo task in background leggerà di continuo da RabbitMQ e manderà alla Dashboard
    asyncio.create_task(consume_rabbitmq())
    # Questo task interroga direttamente il simulatore per gli attuatori
    asyncio.create_task(poll_actuators())
    # Questo task ascolta gli aggiornamenti delle regole in streaming (opzionale se usiamo polling)
    # Tuttavia, l'utente ha chiesto esplicitamente polling ogni 5s usando receive_rules_events
    asyncio.create_task(poll_rules_periodically())

    # ESEMPI DI CHIAMATE rules_manager.py
    # await send_delete_rule(55)
    # await send_insert_rule("sensore_11", "<", 55.0, "attuatore_2", 1)

