# SYSTEM DESCRIPTION:

The Mars IoT Platform is a distributed automation system designed to ensure the survival of astronauts in a Martian habitat. It collects data from a heterogeneous set of sensors (via REST polling and asynchronous Telemetry streams), normalizes this data into a unified internal event schema, and routes it through an event-driven architecture using RabbitMQ. 

The system features an Automation Engine that evaluates active rules against incoming sensor data to automatically trigger life-support actuators, and a web-based Dashboard that allows Mars Operators and Habitat Engineers to monitor real-time metrics, manually control actuators, and manage the automation rules.

# USER STORIES:

1) As a Mars Operator, I want to view a list of all available sensors in the habitat, so that I know what data is currently being monitored.
2) As a Mars Operator, I want to see the real-time value of the greenhouse_temperature, so that I can ensure the crops survive the Martian night.
3) As a Mars Operator, I want to view the latest PM2.5, PM10, and PM1 air quality metrics together, so that I can monitor the safety of the breathable air.
4) As a Mars Operator, I want to visually distinguish sensors that have a "warning" status, so that I can immediately react to hardware anomalies.
5) As a Mars Operator, I want to see the timestamp of the last received measurement for each sensor, so that I know the data is fresh and the sensor is not frozen.
6) As a Mars Operator, I want to monitor the power generation of the solar arrays (kW and Voltage), so that I can ensure the habitat has enough energy.
7) As a Mars Operator, I want to monitor the thermal loop temperature and flow, so that I can prevent the core from overheating.
8) As a Mars Operator, I want to see the current state of the airlock (e.g., PRESSURIZING or DEPRESSURIZING), so that I know if it's safe to initiate an Extravehicular Activity (EVA).
9) As a Mars Operator, I want to see the unit of measurement (e.g., °C, ppm, kW) displayed clearly next to every numerical value, so that I don't misinterpret the readings.
10) As a Mars Operator, I want to view the current ON/OFF state of all habitat actuators, so that I know what life-support equipment is currently running. 
11) As a Mars Operator, I want to manually toggle the habitat_heater, so that I can adjust the ambient comfort level during a sudden temperature drop. 
12) As a Mars Operator, I want to receive immediate visual feedback on the dashboard when an actuator changes state, so that I have confirmation my command was executed successfully.
13) As a Habitat Engineer, I want to create an automation rule using a simple "IF condition THEN action" interface, so that I can automate repetitive safety tasks.
14) As a Habitat Engineer, I want to select the target actuator and its desired state (ON/OFF) when creating a rule, so that the system knows exactly what action to take.
15) As a Habitat Engineer, I want to view a complete list of all active automation rules on the dashboard, so that I can audit the current logical behavior of the habitat. 
16) As a Habitat Engineer, I want to delete an existing automation rule, so that I can safely remove outdated logic from the system.
17) As a Mars Operator, I want the dashboard to update automatically without refreshing the page (via WebSocket or SSE), so that I never miss critical thermodynamic events.
18) As a Mars Operator, I want to easily filter the dashboard widgets to only show sensors with a "warning" status, so that I can focus entirely on emergencies during a crisis. 
19) As a Mars Operator, I want the dashboard to show a disconnected/offline indicator if the connection to the backend drops, so that I don't trust stale dashboard data. 
20) As a Habitat Engineer, I want to see the underlying source protocol (REST or TELEMETRY) for a sensor displayed in its details, so that I can quickly debug connectivity or polling issues.


# CONTAINERS:

## CONTAINER_NAME: mars_simulator

### DESCRIPTION: 
A Docker container simulating a heterogeneous IoT environment on Mars (provided by the assignment). It exposes REST APIs for polling sensors and manipulating actuators, and WebSocket/SSE endpoints for subscribing to asynchronous telemetry streams.

### USER STORIES:
Satisfies the underlying data generation requirements for all monitoring user stories (1-9) and actuator manual control (10-12).

### PORTS: 
8080:8080

### PERSISTENCE EVALUATION
The simulator is stateless with self-generated mocked data; it resets to baseline values upon restart. Disconnected from persistence requirements.

### EXTERNAL SERVICES CONNECTIONS
The simulator does not connect to external services.

### MICROSERVICES:

#### MICROSERVICE: simulator
- TYPE: backend
- DESCRIPTION: Simulates Mars IoT devices. Exposes sensors via REST and Telemetry stream.
- PORTS: 8080
- TECHNOLOGICAL SPECIFICATION:
Developed in Python using the FastAPI framework.


## CONTAINER_NAME: mars_broker

### DESCRIPTION: 
The message broker (RabbitMQ) handling the asynchronous, event-driven communication of the system. It loosely couples the ingestion layer with the processing and dashboard layers.

### USER STORIES:
Enables the event-driven architecture required for real-time monitoring (17).

### PORTS: 
5672:5672 (AMQP)
15672:15672 (Management UI)

### PERSISTENCE EVALUATION
Configured with ephemeral or persistent queues depending on configuration, utilized mostly for transient data delivery without long-term storage requirements. `rules_management` queues declare persistence to ensure no commands drop.

### EXTERNAL SERVICES CONNECTIONS
None.

### MICROSERVICES:

#### MICROSERVICE: rabbitmq
- TYPE: message broker
- DESCRIPTION: RabbitMQ instance routing unified sensor events and automation rule events.
- PORTS: 5672, 15672


## CONTAINER_NAME: mars_ingestion

### DESCRIPTION: 
The ingestion service collects data from the simulated devices (via REST polling and WebSocket streams), normalizes the payloads into a Unified Event Schema, and publishes them to the RabbitMQ broker.

### USER STORIES:
1, 2, 3, 4, 5, 6, 7, 8, 9, 20

### PORTS: 
None published externally.

### PERSISTENCE EVALUATION
The ingestion container is stateless. It translates payloads on-the-fly without requiring internal persistence.

### EXTERNAL SERVICES CONNECTIONS
Connects to `mars_simulator` via HTTP and WS to retrieve data, and to `mars_broker` (RabbitMQ) via AMQP to publish it.

### MICROSERVICES:

#### MICROSERVICE: ingestion
- TYPE: backend
- DESCRIPTION: Collects and normalizes raw REST and Telemetry data into the standard internal event format.
- PORTS: None
- TECHNOLOGICAL SPECIFICATION:
Developed in Python using threading for asynchronous WebSocket clients (websocket-client) and requests for REST API polling. Uses pika to publish to RabbitMQ.
- SERVICE ARCHITECTURE: 
Uses a main execution loop to poll REST endpoints periodically (every 5 seconds) alongside daemon threads that continuously listen to WebSocket telemetry endpoints. All received JSON payloads map to standard data dictionaries representing single metrics before publishing to the Fanout exchange `mars_events`.

- ENDPOINTS: No exposed endpoints.


## CONTAINER_NAME: mars_automation_engine

### DESCRIPTION: 
Evaluates simple event-triggered rules dynamically as telemetry arrives. If conditions match, it seamlessly triggers the corresponding actuator on the simulator.

### USER STORIES:
13, 14, 16 (backend fulfillment)

### PORTS: 
None published externally.

### PERSISTENCE EVALUATION
Requires connection to a persistent relational database (PostgreSQL) to store rules and load them into memory upon boot, ensuring rules survive service restarts.

### EXTERNAL SERVICES CONNECTIONS
Connects to `mars_broker` for incoming sensor metrics and rule commands. Connects to `postgres_db` to read/write rules. Connects to `mars_simulator` via REST to trigger actuators.

### MICROSERVICES:

#### MICROSERVICE: automation-engine
- TYPE: backend
- DESCRIPTION: Evaluates sensor events against active rules and triggers actuators.
- PORTS: None
- TECHNOLOGICAL SPECIFICATION:
Developed in Python using a hybrid pika/aio_pika setup and psycopg2. Uses threading alongside an asyncio loop.
- SERVICE ARCHITECTURE: 
Features a primary `pika` blocking loop listening to the `mars_events` exchange to evaluate incoming metrics. Concurrently runs an `aio_pika` asyncio loop listening to the `rules_management` exchange to insert/delete rules in the database and broadcast the list of current active rules back to the broker.

- ENDPOINTS: No exposed endpoints.

- DB STRUCTURE: 
Reads from and writes to the `rules` table. See PostgreSQL container details.


## CONTAINER_NAME: postgres_db

### DESCRIPTION: 
A PostgreSQL database responsible for securely persisting the Automation Rules mapped by the Habitat Engineer, ensuring rules do not wipe if the backend drops.

### USER STORIES:
13, 14, 15, 16

### PORTS: 
5433:5432

### PERSISTENCE EVALUATION
This container holds persistent information; it utilizes a Docker Volume (`postgres_data`) mapped to `/var/lib/postgresql/data` to ensure true data persistence.

### EXTERNAL SERVICES CONNECTIONS
None.

### MICROSERVICES:

#### MICROSERVICE: postgres
- TYPE: database
- DESCRIPTION: Standard PostgreSQL Database storing valid IoT fields and active Automation Rules.
- PORTS: 5433
- TECHNOLOGICAL SPECIFICATION:
Standard PostgreSQL image.
- DB STRUCTURE: 

	**_rules_** :	| **_id_** (SERIAL) | sensor_name (VARCHAR) | operator (VARCHAR) | value (NUMERIC) | actuator_name (VARCHAR) | On_off (INTEGER) |
	**_sensors_** :	| **_name_** (VARCHAR) |
	**_actuators_** :	| **_name_** (VARCHAR) |
	**_operators_** :	| **_symbol_** (VARCHAR) |


## CONTAINER_NAME: mars_dashboard

### DESCRIPTION: 
A web-based graphical interface for Mars Operators and Habitat Engineers. Exposes a live-updated UI utilizing WebSockets with a Python FastAPI backend.

### USER STORIES:
All UI components related to monitoring (1-9), actuator toggles (10-12), rule creation interfaces (13-16) and UI real-time UX conditions (17-20).

### PORTS: 
8000:8000

### PERSISTENCE EVALUATION
The Dashboard backend maintains an in-memory dictionary of the latest sensor states strictly for routing, but leverages external brokers/databases for core rule persistence.

### EXTERNAL SERVICES CONNECTIONS
Connects to `mars_broker` to stream `mars_events` and `rules_management` events to frontend UI. Connects to `mars_simulator` for HTTP proxies to manually toggle actuators.

### MICROSERVICES:

#### MICROSERVICE: dashboard
- TYPE: frontend & backend
- DESCRIPTION: Serves the static HTML/JS frontend and bridges the RabbitMQ message broker to the browser via WebSockets.
- PORTS: 8000
- TECHNOLOGICAL SPECIFICATION:
Backend: Python with FastAPI, Uvicorn, and aio_pika to bridge AMQP to WebSockets.
Frontend: Vanilla JS, raw HTML, and CSS (stored in the `/static` folder). No complex JS frameworks.
- SERVICE ARCHITECTURE: 
A FastAPI app serving a static HTML directory. Defines a `/ws` WebSocket endpoint through which the main loop broadcasts broker JSON payloads down to connected browser clients. Employs proxy REST endpoints to mask direct simulator/rule calls.

- ENDPOINTS: 
		
	| HTTP METHOD | URL | Description | User Stories |
	| ----------- | --- | ----------- | ------------ |
	| GET | /ws | WebSocket Upgrade endpoint. Pushes real-time unified events and active rule lists to the browser. | 1-9, 15, 17, 18, 19, 20 |
	| POST | /actuators/{name} | Proxy endpoint: sends an ON/OFF state command to a simulated actuator. | 11 |
	| POST | /rules | Publishes a message to the broker to insert a rule. | 13, 14 |
	| DELETE | /rules/{rule_id} | Publishes a message to the broker to delete a rule. | 16 |

- PAGES: 
	
	| Name | Description | Related Microservice | User Stories |
	| ---- | ----------- | -------------------- | ------------ |
	| index.html | Single Page Application presenting live widgets, a rule table, and actuator toggles. | mars_dashboard | All |
