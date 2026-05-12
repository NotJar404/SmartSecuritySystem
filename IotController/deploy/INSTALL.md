# 🔐 Smart Security System — Complete Raspberry Pi Deployment Guide

> **SecureVision AI-Assisted Smart Security & Intrusion Detection System**
> Full deployment from development machine to Raspberry Pi 5

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Architecture Overview](#architecture)
3. [Step 1: Raspberry Pi OS Setup](#step-1-raspberry-pi-os-setup)
4. [Step 2: PostgreSQL Database](#step-2-postgresql-database)
5. [Step 3: ASP.NET Backend](#step-3-aspnet-backend)
6. [Step 4: Python IoT Controller](#step-4-python-iot-controller)
7. [Step 5: Hardware Wiring](#step-5-hardware-wiring)
8. [Step 6: NGINX Reverse Proxy](#step-6-nginx-reverse-proxy)
9. [Step 7: Auto-Start Services](#step-7-auto-start-services)
10. [Step 8: Testing & Validation](#step-8-testing--validation)
11. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Hardware Required

| Component | Model | Purpose |
|-----------|-------|---------|
| Single Board Computer | Raspberry Pi 5 (4GB) | Main controller |
| Camera | Pi Camera Module 3 | Face detection + occupancy |
| Motion Sensor | PIR HC-SR501 | Motion-based wake/sleep |
| RFID Reader | RC522 (MFRC522) | Card-based access control |
| Door Lock | 12V Solenoid Lock | Physical access control |
| Relay | 5V Relay Module | Solenoid driver (12V isolation) |
| Buzzer | Active Buzzer (3-24V) | Audio alerts |
| LED | Common Cathode RGB LED | Visual status indicator |
| Door Sensor | Magnetic Reed Switch | Forced entry detection |
| Power | 12V 2A PSU + Pi 5 PSU | Power supply |
| Storage | 32GB+ MicroSD (A2) | OS + data |
| Misc | 3x 220Ω resistors, jumper wires, breadboard | Wiring |

### Software Required (on Development Machine)

| Software | Version | Purpose |
|----------|---------|---------|
| .NET SDK | 8.0+ | ASP.NET build |
| PostgreSQL | 14+ | Database |
| Git | Latest | Version control |
| PuTTY or Terminal | Any | SSH access to Pi |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    RASPBERRY PI 5                            │
│                                                              │
│  ┌─────────────────┐    ┌──────────────────────────────────┐ │
│  │  Python IoT      │    │  ASP.NET MVC (Kestrel :5145)     │ │
│  │  Controller      │───►│  - Dashboard                     │ │
│  │  (main.py)       │    │  - Access Control                │ │
│  │                   │    │  - Personnel Management          │ │
│  │  ├─ Camera       │    │  - System Settings               │ │
│  │  ├─ RFID Reader  │    │  - Alerts                        │ │
│  │  ├─ PIR Sensor   │    │  - Analytics                     │ │
│  │  ├─ Solenoid     │    └────────────┬─────────────────────┘ │
│  │  ├─ Buzzer       │                 │                       │
│  │  ├─ RGB LED      │    ┌────────────▼─────────────────────┐ │
│  │  └─ Door Sensor  │    │  PostgreSQL (localhost:5432)      │ │
│  └─────────┬────────┘    │  Database: SmartSecurityDB        │ │
│            │              └──────────────────────────────────┘ │
│  ┌─────────▼────────┐    ┌──────────────────────────────────┐ │
│  │  Flask MJPEG      │    │  NGINX (port 80/443)             │ │
│  │  Stream (:5050)   │    │  Reverse Proxy → Kestrel :5145   │ │
│  └──────────────────┘    └──────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

---

## Step 1: Raspberry Pi OS Setup

### 1.1 Flash OS

1. Download [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
2. Flash **Raspberry Pi OS (64-bit, Bookworm)** to MicroSD
3. In Imager settings (gear icon):
   - Enable SSH
   - Set username: `pi`, password: your choice
   - Configure WiFi (or use Ethernet)
4. Insert SD card and boot

### 1.2 Enable Hardware Interfaces

```bash
sudo raspi-config
```

Enable under **Interface Options**:
- **SPI** → Enable (for RC522 RFID)
- **I2C** → Enable (optional, future sensors)
- **Camera** → Enable (Pi Camera Module 3)

```bash
sudo reboot
```

### 1.3 Update System

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl wget nano htop
```

---

## Step 2: PostgreSQL Database

### 2.1 Install PostgreSQL

```bash
sudo apt install -y postgresql postgresql-contrib
sudo systemctl enable postgresql
sudo systemctl start postgresql
```

### 2.2 Create Database & User

```bash
sudo -u postgres psql
```

```sql
CREATE USER postgres WITH PASSWORD '1234';
ALTER USER postgres WITH SUPERUSER;
CREATE DATABASE "SmartSecurityDB" OWNER postgres;
\q
```

### 2.3 Configure Remote Access (if needed)

```bash
# Allow local connections with password
sudo nano /etc/postgresql/15/main/pg_hba.conf
```

Change `local all all peer` to:
```
local   all   all   md5
```

```bash
sudo systemctl restart postgresql
```

### 2.4 Import Database Schema

Transfer your existing database dump from development machine:

```bash
# On development machine (Windows PowerShell):
pg_dump -U postgres -h localhost SmartSecurityDB > smartsecurity_dump.sql

# Copy to Pi via SCP:
scp smartsecurity_dump.sql pi@<PI_IP>:/home/pi/
```

```bash
# On Raspberry Pi:
sudo -u postgres psql SmartSecurityDB < /home/pi/smartsecurity_dump.sql
```

### 2.5 Verify Tables Exist

```bash
sudo -u postgres psql SmartSecurityDB
```

```sql
\dt
```

You should see these tables:
```
 authorized_personnel    | rooms                | access_logs
 alerts                  | camera_devices       | detection_logs
 alarm_settings          | room_occupancy       | notifications
 occupancy_sessions      | recordings           | login_logs
 users                   | person_room_access   |
```

---

## Step 3: ASP.NET Backend

### 3.1 Install .NET 8 Runtime

```bash
# Install .NET 8 SDK + Runtime for ARM64
curl -sSL https://dot.net/v1/dotnet-install.sh | bash /dev/stdin --channel 8.0

# Add to PATH permanently
echo 'export DOTNET_ROOT=$HOME/.dotnet' >> ~/.bashrc
echo 'export PATH=$PATH:$DOTNET_ROOT:$DOTNET_ROOT/tools' >> ~/.bashrc
source ~/.bashrc

# Verify
dotnet --version
```

### 3.2 Transfer & Build Project

```bash
# Clone or copy project to Pi
cd /home/pi
git clone <your-repo-url> SmartSecuritySystem

# Build the ASP.NET app
cd SmartSecuritySystem/WebApp
dotnet restore
dotnet publish -c Release -o /home/pi/SmartSecuritySystem/publish
```

### 3.3 Configure Connection String

Edit `appsettings.json` in the publish folder:

```bash
nano /home/pi/SmartSecuritySystem/publish/appsettings.json
```

Ensure the connection string matches your Pi's PostgreSQL:

```json
{
  "ConnectionStrings": {
    "DefaultConnection": "Host=localhost;Port=5432;Database=SmartSecurityDB;Username=postgres;Password=1234"
  },
  "AllowedHosts": "*"
}
```

### 3.4 Test ASP.NET

```bash
cd /home/pi/SmartSecuritySystem/publish
dotnet WebApp.dll --urls "http://0.0.0.0:5145"
```

Open browser: `http://<PI_IP>:5145` — you should see the login page.

---

## Step 4: Python IoT Controller

### 4.1 Install System Dependencies

```bash
# Camera support
sudo apt install -y python3-libcamera python3-picamera2 libcamera-apps

# OpenCV dependencies
sudo apt install -y python3-opencv libopencv-dev

# GStreamer (for libcamera → OpenCV pipeline)
sudo apt install -y gstreamer1.0-tools gstreamer1.0-plugins-good gstreamer1.0-plugins-bad

# Face recognition build dependencies
sudo apt install -y cmake build-essential libdlib-dev python3-dev

# GPIO permissions
sudo usermod -aG gpio,spi,i2c,video pi
```

### 4.2 Create Virtual Environment

```bash
cd /home/pi/SmartSecuritySystem/IotController

python3 -m venv ../venv --system-site-packages
source ../venv/bin/activate
```

> **`--system-site-packages`** is CRITICAL — it allows access to `picamera2` and `libcamera` which are system-installed.

### 4.3 Install Python Dependencies

```bash
pip install --upgrade pip

# Core packages
pip install opencv-python-headless numpy requests flask

# Raspberry Pi hardware
pip install RPi.GPIO mfrc522

# Face recognition (takes ~30 min on Pi — needs dlib compilation)
pip install face_recognition
```

> ⚠️ **If dlib compilation fails (out of memory):**
> ```bash
> sudo dphys-swapfile swapoff
> sudo sed -i 's/CONF_SWAPSIZE=.*/CONF_SWAPSIZE=2048/' /etc/dphys-swapfile
> sudo dphys-swapfile setup
> sudo dphys-swapfile swapon
> # Then retry: pip install face_recognition
> # After success, reduce swap back to 200MB
> ```

### 4.4 Download AI Models

```bash
cd /home/pi/SmartSecuritySystem/IotController
python models/download_model.py
```

### 4.5 Configure Backend URL

Edit `main.py` — find the `main()` function at the bottom and set `base_url`:

```python
system = SmartSecuritySystem(
    use_simulated_rfid=False,
    # base_url="http://localhost:5145" is set automatically from ASPNETCORE_HTTP_PORT env var
    camera_id=1,
    room_id=1,                          # Room this reader is assigned to
    max_stay_minutes=20,
    room_max_capacity=10,
    operating_hours_start=6,
    operating_hours_end=22
)
```

### 4.6 Test IoT Controller

```bash
cd /home/pi/SmartSecuritySystem/IotController
source ../venv/bin/activate
python main.py
```

Expected output:
```
==================================================
[SYSTEM] Smart Security System — State-Based FSM
==================================================
[CAMERA] ✓ Pi Camera Module 3 via libcamera (GStreamer)
[PIR] Initialized on GPIO pin 17
[LOCK] Initialized on GPIO pin 18
[BUZZER] Initialized on GPIO pin 24
[RGB LED] Initialized on GPIO pins R=5, G=6, B=13
[DOOR] Initialized on GPIO pin 16 — CLOSED
[FSM] Initial state: IDLE
[SYSTEM] Initialization complete
[RFID] Reader started (RC522 HARDWARE)

==================================================
 FSM Security System Running [RASPBERRY PI]
 Press Ctrl+C to stop
==================================================
```

---

## Step 5: Hardware Wiring

### 5.1 Complete GPIO Pin Map

```
┌─────────────────────────────────────────────────────────────────┐
│                    RASPBERRY PI 5 — GPIO PINOUT                  │
│                                                                  │
│  BCM Pin  │  Physical Pin  │  Component          │  Direction   │
│───────────┼────────────────┼─────────────────────┼──────────────│
│  GPIO 17  │  Pin 11        │  PIR HC-SR501       │  INPUT       │
│  GPIO 18  │  Pin 12        │  Relay → Solenoid   │  OUTPUT      │
│  GPIO 24  │  Pin 18        │  Active Buzzer      │  OUTPUT      │
│  GPIO 5   │  Pin 29        │  RGB LED — Red      │  OUTPUT      │
│  GPIO 6   │  Pin 31        │  RGB LED — Green    │  OUTPUT      │
│  GPIO 13  │  Pin 33        │  RGB LED — Blue     │  OUTPUT      │
│  GPIO 16  │  Pin 36        │  Magnetic Door Snsr │  INPUT PU    │
│  GPIO 8   │  Pin 24 (CE0)  │  RC522 RFID — SDA   │  SPI         │
│  GPIO 11  │  Pin 23        │  RC522 RFID — SCK   │  SPI         │
│  GPIO 10  │  Pin 19        │  RC522 RFID — MOSI  │  SPI         │
│  GPIO 9   │  Pin 21        │  RC522 RFID — MISO  │  SPI         │
│  GPIO 25  │  Pin 22        │  RC522 RFID — RST   │  OUTPUT      │
│  3.3V     │  Pin 1         │  RC522 RFID — VCC   │  Power       │
│  GND      │  Pin 6,9,etc   │  Common Ground      │  Ground      │
│  CSI      │  Ribbon Cable  │  Camera Module 3    │  CSI Port    │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 RC522 RFID Reader Wiring

```
RC522 Pin    →    Raspberry Pi Pin
─────────────────────────────────
SDA          →    GPIO 8  (Pin 24, CE0)
SCK          →    GPIO 11 (Pin 23)
MOSI         →    GPIO 10 (Pin 19)
MISO         →    GPIO 9  (Pin 21)
IRQ          →    Not Connected
GND          →    GND     (Pin 6)
RST          →    GPIO 25 (Pin 22)
3.3V         →    3.3V    (Pin 1)
```

> ⚠️ **RC522 is 3.3V ONLY** — connecting to 5V will damage it.

### 5.3 PIR Motion Sensor Wiring

```
PIR HC-SR501    →    Raspberry Pi
────────────────────────────────
VCC             →    5V    (Pin 2 or 4)
OUT             →    GPIO 17 (Pin 11)
GND             →    GND   (Pin 6)
```

**PIR Adjustment:**
- **Sensitivity potentiometer**: Turn clockwise for higher range
- **Delay potentiometer**: Set to minimum (~3s) — software handles timing
- **Jumper**: Set to **H** (repeatable trigger mode)

### 5.4 Solenoid Lock Wiring (via Relay)

```
                ┌──────────────────┐
GPIO 18 ────→──│ IN    5V Relay   │──→── 12V Solenoid Lock
Pi 5V   ────→──│ VCC   Module     │       (NO + COM terminals)
Pi GND  ────→──│ GND              │
                └────────┬─────────┘
                         │
         12V PSU (+) ───→ Relay COM
         12V PSU (-) ───→ Solenoid other terminal
```

> ⚠️ **NEVER connect 12V directly to GPIO!** Always use a relay module.
> The relay acts as an electrically isolated switch.

### 5.5 Active Buzzer Wiring

```
Buzzer (+)  →    GPIO 24 (Pin 18)
Buzzer (-)  →    GND     (Pin 9)
```

> Use a transistor (2N2222) if buzzer draws >16mA.

### 5.6 RGB LED Wiring (Common Cathode)

```
Red Anode   →    220Ω Resistor → GPIO 5  (Pin 29)
Green Anode →    220Ω Resistor → GPIO 6  (Pin 31)
Blue Anode  →    220Ω Resistor → GPIO 13 (Pin 33)
Cathode (-) →    GND            (Pin 14)
```

### 5.7 Magnetic Door Sensor Wiring

```
Reed Switch Wire 1  →    GPIO 16 (Pin 36)
Reed Switch Wire 2  →    GND     (Pin 39)
```

Software enables internal pull-up resistor. Door CLOSED = circuit closed = LOW.

### 5.8 Camera Module 3

1. Power off the Pi completely
2. Lift the CSI connector latch on the Pi board
3. Insert the ribbon cable (blue side facing USB ports)
4. Press latch down firmly
5. Boot and test: `libcamera-hello --timeout 3000`

---

## Step 6: NGINX Reverse Proxy

### 6.1 Install NGINX

```bash
sudo apt install -y nginx
```

### 6.2 Configure Site

```bash
sudo nano /etc/nginx/sites-available/smartsecurity
```

```nginx
server {
    listen 80;
    server_name _;

    # ASP.NET MVC Application
    location / {
        proxy_pass http://127.0.0.1:5145;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection keep-alive;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
    }

    # MJPEG Camera Stream (proxied from Python Flask)
    location /video {
        proxy_pass http://127.0.0.1:5050/video;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_cache off;
        chunked_transfer_encoding off;
    }

    # Python Flask status/health API proxy
    location /status {
        proxy_pass http://127.0.0.1:5050/status;
    }

    location /health {
        proxy_pass http://127.0.0.1:5050/health;
    }
}
```

### 6.3 Enable Site

```bash
sudo ln -sf /etc/nginx/sites-available/smartsecurity /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx
sudo systemctl enable nginx
```

---

## Step 7: Auto-Start Services

### 7.1 ASP.NET Service

```bash
sudo nano /etc/systemd/system/webapp.service
```

```ini
[Unit]
Description=SecureVision ASP.NET Web Application
After=network.target postgresql.service

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/SmartSecuritySystem/publish
ExecStart=/home/pi/.dotnet/dotnet WebApp.dll --urls "http://0.0.0.0:5145"
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment=ASPNETCORE_ENVIRONMENT=Production
Environment=DOTNET_ROOT=/home/pi/.dotnet

[Install]
WantedBy=multi-user.target
```

### 7.2 Python IoT Service

```bash
sudo cp /home/pi/SmartSecuritySystem/IotController/deploy/smartsecurity.service \
        /etc/systemd/system/smartsecurity.service
```

The service file (`smartsecurity.service`) is already included in the repo:

```ini
[Unit]
Description=Smart Security System - FSM Controller
After=network.target webapp.service
Wants=webapp.service

[Service]
Type=simple
User=pi
Group=pi
WorkingDirectory=/home/pi/SmartSecuritySystem/IotController
ExecStart=/home/pi/SmartSecuritySystem/venv/bin/python main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1
SupplementaryGroups=gpio spi i2c video

[Install]
WantedBy=multi-user.target
```

### 7.3 Enable & Start All Services

```bash
sudo systemctl daemon-reload

# Enable auto-start on boot
sudo systemctl enable postgresql
sudo systemctl enable nginx
sudo systemctl enable webapp
sudo systemctl enable smartsecurity

# Start services
sudo systemctl start webapp
sleep 5   # Wait for ASP.NET to be ready
sudo systemctl start smartsecurity
```

### 7.4 Service Management

```bash
# Check status
sudo systemctl status webapp
sudo systemctl status smartsecurity

# View logs
journalctl -u webapp -f
journalctl -u smartsecurity -f

# Restart after code changes
sudo systemctl restart webapp && sudo systemctl restart smartsecurity
```

---

## Step 8: Testing & Validation

### 8.1 Test Individual Sensors

```bash
cd /home/pi/SmartSecuritySystem/IotController
source ../venv/bin/activate

# Camera
python -c "from Sensors.camera_module import CameraModule; c = CameraModule(); print(c.initialize())"

# PIR
python -c "from Sensors.pir_sensor import PIRSensor; p = PIRSensor(); p.initialize(); print('PIR OK')"

# RFID (hold card to reader within 10s)
python -c "from Sensors.rfid_reader import RFIDReader; r = RFIDReader(); r.start_reading(lambda uid: print(f'Card: {uid}')); import time; time.sleep(10)"

# Buzzer
python -c "from Sensors.hardware import Buzzer; b = Buzzer(); b.initialize(); b.beep(1); import time; time.sleep(2); b.cleanup()"

# RGB LED
python -c "from Sensors.hardware import RGBLed; l = RGBLed(); l.initialize(); l.status_idle(); import time; time.sleep(3); l.cleanup()"

# Door Sensor
python -c "from Sensors.hardware import DoorSensor; d = DoorSensor(); d.initialize(); print('Door:', 'OPEN' if d.is_door_open() else 'CLOSED')"

# Solenoid Lock
python -c "from Sensors.lock_sensor import SolenoidLock; s = SolenoidLock(); s.initialize(); s.unlock(3); import time; time.sleep(5); s.cleanup()"
```

### 8.2 Test API Endpoints

```bash
# RFID lookup with room access check
curl http://localhost:5145/api/access/rfid?uid=TEST123&roomId=1

# Room list for a person
curl http://localhost:5145/api/access/room-list?personId=1

# Available rooms
curl http://localhost:5145/api/access/rooms

# System status
curl http://localhost:5145/api/system/status

# Pi health
curl http://localhost:5145/api/system/pi-health

# Camera stream
curl -I http://localhost:5050/video
```

### 8.3 Full Integration Test

1. **Login**: Open `http://<PI_IP>` → Login with admin credentials
2. **Dashboard**: Verify camera stream shows live feed
3. **RFID Test**: Tap a registered card → verify access granted + door unlocks
4. **Room Access**: In Personnel → assign a room → verify RFID works for that room
5. **Unknown Card**: Tap unregistered card → verify yellow LED + buzzer + log entry
6. **Emergency**: System Settings → Activate Intruder Alert → verify overlay + hardware
7. **Lockdown**: Dashboard → Activate Lockdown → verify red overlay + door locks

---

## Troubleshooting

### Camera not detected
```bash
libcamera-hello --timeout 3000      # Test camera directly
ls -la /dev/video*                   # Check V4L2 devices
vcgencmd get_camera                  # Check firmware detection
sudo raspi-config                    # Interface Options → Camera
```

### RFID not reading
```bash
ls /dev/spi*                         # Should show spidev0.0, spidev0.1
lsmod | grep spi                     # Check SPI kernel module
sudo raspi-config                    # Interface Options → SPI → Enable
```

### Permission errors
```bash
sudo usermod -aG gpio,spi,i2c,video pi
sudo reboot
```

### ASP.NET won't start
```bash
journalctl -u webapp -n 50 --no-pager
# Common fix: connection string wrong
nano /home/pi/SmartSecuritySystem/publish/appsettings.json
```

### Python service crashes
```bash
journalctl -u smartsecurity -n 50 --no-pager
# Test manually:
cd /home/pi/SmartSecuritySystem/IotController
../venv/bin/python main.py
```

### Database connection refused
```bash
sudo systemctl status postgresql
sudo -u postgres psql -c "SELECT 1;"
# Fix pg_hba.conf if needed (see Step 2.3)
```

### Low FPS / High CPU
```bash
htop   # Check CPU usage

# Reduce resolution if needed (in camera_module.py):
# width=640, height=480 instead of 1280x720

# Ensure swap is reduced after dlib compilation:
sudo sed -i 's/CONF_SWAPSIZE=.*/CONF_SWAPSIZE=200/' /etc/dphys-swapfile
sudo dphys-swapfile setup
sudo dphys-swapfile swapon
```

### Door sensor reads wrong
```bash
# Test manually
python -c "
import RPi.GPIO as GPIO
GPIO.setmode(GPIO.BCM)
GPIO.setup(16, GPIO.IN, pull_up_down=GPIO.PUD_UP)
import time
while True:
    print('OPEN' if GPIO.input(16) else 'CLOSED')
    time.sleep(1)
"
```

---

## Quick Reference: System Access Points

| Service | URL | Port |
|---------|-----|------|
| Web Dashboard | `http://<PI_IP>/` | 80 (NGINX) |
| ASP.NET Direct | `http://<PI_IP>:5145` | 5145 |
| Camera Stream | `http://<PI_IP>:5050/stream` | 5050 |
| PostgreSQL | `localhost` | 5432 |

## Quick Reference: Service Commands

```bash
# Start everything
sudo systemctl start postgresql nginx webapp smartsecurity

# Stop everything
sudo systemctl stop smartsecurity webapp nginx

# Restart after update
sudo systemctl restart webapp && sleep 3 && sudo systemctl restart smartsecurity

# View all logs
journalctl -u webapp -u smartsecurity -f
```
