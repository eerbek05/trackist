CREATE TABLE IF NOT EXISTS flights (
    flight_id VARCHAR(10) PRIMARY KEY,
    from_airport VARCHAR(100),
    to_airport VARCHAR(100),
    speed_kmh INTEGER,
    altitude_ft INTEGER,
    departure VARCHAR(10),
    arrival VARCHAR(10),
    aircraft VARCHAR(50),
    status VARCHAR(20),
    duration_minutes INTEGER
);

INSERT INTO flights VALUES ('TK2200', 'İstanbul (IST)', 'New York (JFK)', 905, 38000, '10:30', '14:45', 'Boeing 777-300ER', 'Havada', 675);
INSERT INTO flights VALUES ('TK1', 'İstanbul (IST)', 'Londra (LHR)', 870, 36000, '08:00', '10:20', 'Airbus A330-300', 'Havada', 200);
INSERT INTO flights VALUES ('PC401', 'İstanbul (SAW)', 'Ankara (ESB)', 720, 29000, '14:00', '15:10', 'Boeing 737-800', 'İndi', 70);