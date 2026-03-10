# 1933280_GWAN
Laboratory of Advanced Programming GWAN's Project

## Quick Start

Follow these steps to deploy and run the Mars IoT Automation Platform on your local machine.

### Prerequisites
- Ensure **Docker** and **Docker Compose** are installed and currently running on your system.
- You must have the simulator image archive (`mars-iot-simulator-oci.tar`) provided with the hackathon materials.

### Installation & Run Instructions

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Armando-96/1933280_GWAN.git
   cd 1933280_GWAN
   ```

2. **Load the Mars IoT Simulator image:**
   If the simulator Docker image is not already present in your local environment, you need to load it manually from the provided `.tar` archive:
   ```bash
   docker load -i mars-iot-simulator-oci.tar
   ```

3. **Navigate to the `source` directory:**
   All the source code, Dockerfiles, and the `docker-compose.yml` file needed to deploy the system are located in the `source` folder:
   ```bash
   cd source
   ```

4. **Start the platform:**
   Launch the entire system (Simulator, RabbitMQ Message Broker, Ingestion Service, Automation Engine, PostgreSQL Database, and the Dashboard) by running:
   ```bash
   docker compose up
   ```

5. **Access the Dashboard:**
   Once all containers are successfully up and running, open your web browser and navigate to:
   **http://localhost:8000**


credentials to log into postgres (for debugging purposes only) :
user = "admin"
password = "password"
port= 5433
mantainance database = "mars"

credentials to log into RabbitMQ dashboard (for debugging purposes):
user= "admin"
password= "admin"
url = http://localhost:15672/
