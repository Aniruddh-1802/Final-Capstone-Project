-- Run once as a MySQL administrator (root). Replace the password placeholder before running;
-- do NOT commit a real password.
CREATE DATABASE IF NOT EXISTS healthcare_db
  CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE DATABASE IF NOT EXISTS healthcare_test
  CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE USER IF NOT EXISTS 'hc_app'@'localhost' IDENTIFIED BY 'CHANGE_ME';
CREATE USER IF NOT EXISTS 'hc_app'@'127.0.0.1' IDENTIFIED BY 'CHANGE_ME';

GRANT ALL PRIVILEGES ON healthcare_db.*   TO 'hc_app'@'localhost';
GRANT ALL PRIVILEGES ON healthcare_test.* TO 'hc_app'@'localhost';
GRANT ALL PRIVILEGES ON healthcare_db.*   TO 'hc_app'@'127.0.0.1';
GRANT ALL PRIVILEGES ON healthcare_test.* TO 'hc_app'@'127.0.0.1';
FLUSH PRIVILEGES;
