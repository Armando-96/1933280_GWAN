
DROP TABLE IF EXISTS rules;
DROP TABLE IF EXISTS sensors;
DROP TABLE IF EXISTS actuators;
DROP TABLE IF EXISTS operators;

-- SENSORS
CREATE TABLE sensors (
    name VARCHAR(100) PRIMARY KEY
);

INSERT INTO sensors (name) VALUES
    ('greenhouse_temperature'),
    ('entrance_humidity'),
    ('co2_hall'),
    ('hydroponic_ph'),
    ('water_tank_level'),
    ('corridor_pressure'),
    ('air_quality_pm25'),
    ('air_quality_voc');

-- ACTUATORS
CREATE TABLE actuators (
    name VARCHAR(100) PRIMARY KEY
);

INSERT INTO actuators (name) VALUES
    ('cooling_fan'),
    ('entrance_humidifier'),
    ('hall_ventilation'),
    ('habitat_heater');

--  OPERATORS
CREATE TABLE operators (
    symbol VARCHAR(5) PRIMARY KEY
);

INSERT INTO operators (symbol) VALUES
    ('<'),
    ('<='),
    ('='),
    ('>'),
    ('>=');

-- RULES 
CREATE TABLE rules (
    id SERIAL PRIMARY KEY,
    sensor_name VARCHAR(100) NOT NULL REFERENCES sensors(name),
    operator VARCHAR(5) NOT NULL REFERENCES operators(symbol),
    value NUMERIC NOT NULL,
    actuator_name VARCHAR(100) NOT NULL REFERENCES actuators(name),
    On_off INTEGER NOT NULL CHECK (On_off IN (0, 1))
);

--TEST INSERTS
INSERT INTO rules (sensor_name, operator, value, actuator_name, On_off) VALUES
    ('greenhouse_temperature', '>', 25.0, 'cooling_fan', 1),    
    ('entrance_humidity', '<', 40, 'entrance_humidifier', 1),   
    ('corridor_pressure', '>', 100, 'hall_ventilation', 1),      
    ('greenhouse_temperature', '<', 18, 'habitat_heater', 1);   