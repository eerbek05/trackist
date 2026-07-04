-- Deterministic eval fixtures. Loading wipes the flights table so every
-- expected answer in dataset.py is exactly derivable from these rows.
-- updated_at is written fresh (UTC) so nothing is filtered out as stale.

DELETE FROM flights;

INSERT INTO flights (
    flight_id, flight_icao, from_airport, to_airport, speed_kmh, altitude_ft,
    departure, arrival, aircraft, status, updated_at, lat, lng, heading,
    prev_altitude_ft, v_speed_fpm, dep_gate, arr_gate, dep_terminal,
    arr_terminal, arr_baggage, dep_delayed, arr_delayed, dep_estimated, arr_estimated
) VALUES
-- Fastest flight, departing IST, delayed 25, gate F6, climbing
('TK9001', 'THY9001', 'IST', 'JFK', 900, 36000,
 '2026-07-04 08:00', '2026-07-04 18:30', 'B77W', 'en-route',
 (NOW() AT TIME ZONE 'UTC'), 45.0, -30.0, 270,
 35000, 12, 'F6', NULL, 'I', '1', NULL, 25, 25, '2026-07-04 08:25', '2026-07-04 18:55'),

-- Landed at IST, baggage belt 7
('EK9002', 'UAE9002', 'DXB', 'IST', 0, 0,
 '2026-07-04 05:10', '2026-07-04 09:40', 'A388', 'landed',
 (NOW() AT TIME ZONE 'UTC'), 41.2753, 28.7519, 40,
 500, NULL, NULL, '212', NULL, '1', '7', NULL, NULL, NULL, '2026-07-04 09:38'),

-- Arriving at IST, most delayed (45 min)
('LH9003', 'DLH9003', 'FRA', 'IST', 800, 30000,
 '2026-07-04 09:00', '2026-07-04 12:10', 'A321', 'en-route',
 (NOW() AT TIME ZONE 'UTC'), 44.5, 20.3, 115,
 31000, -8, 'A22', '305', '1', '1', '12', 45, 45, '2026-07-04 09:45', '2026-07-04 12:55'),

-- Slowest airborne flight
('PC9004', 'PGT9004', 'IST', 'LHR', 400, 20000,
 '2026-07-04 10:00', '2026-07-04 13:50', 'B738', 'en-route',
 (NOW() AT TIME ZONE 'UTC'), 47.1, 15.2, 300,
 19000, 3, 'B4', NULL, '1', '2', NULL, NULL, NULL, NULL, NULL),

-- Scheduled TK narrow-body (seat-map case: A321, 12A window / 12C aisle)
('TK9005', 'THY9005', 'IST', 'ESB', 0, 0,
 '2026-07-04 22:15', '2026-07-04 23:20', 'A321', 'scheduled',
 (NOW() AT TIME ZONE 'UTC'), NULL, NULL, NULL,
 NULL, NULL, 'D2', NULL, 'I', NULL, NULL, NULL, NULL, NULL, NULL),

-- Highest flight, arriving IST from Doha
('QR9006', 'QTR9006', 'DOH', 'IST', 850, 41000,
 '2026-07-04 07:30', '2026-07-04 12:40', 'B788', 'en-route',
 (NOW() AT TIME ZONE 'UTC'), 36.9, 33.5, 320,
 41000, 0, 'C11', '308', '1', '1', '9', NULL, NULL, NULL, '2026-07-04 12:40');
