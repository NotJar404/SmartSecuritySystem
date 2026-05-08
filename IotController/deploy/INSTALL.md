# Raspberry Pi 5 — Installation & Deployment Guide

## Prerequisites

- Raspberry Pi 5 (4GB) with Raspberry Pi OS (64-bit, Bookworm)
- All hardware components connected (see GPIO Wiring below)
- ASP.NET backend running on a machine accessible from Pi's network
- SSH access to the Pi

---

## Step 1: Enable Hardware Interfaces

```bash
sudo raspi-config
```

Enable the following under **Interface Options**:
- **SPI** → Enable (for RC522 RFID)
- **I2C** → Enable (optional, for future sensors)
- **Camera** → Enable (for Pi Camera Module 3)

Then reboot:
```bash
sudo reboot
```

---

## Step 2: Install System Dependencies

```bash
# Update system
sudo apt update && sudo apt upgrade -y

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

---

## Step 3: Clone and Setup Project

```bash
cd /home/pi
git clone <your-repo-url> SmartSecuritySystem

cd SmartSecuritySystem/IotController

# Create virtual environment
python3 -m venv ../venv
source ../venv/bin/activate

# Install Python dependencies
pip install --upgrade pip
pip install opencv-python-headless numpy requests flask

# Pi-specific packages
pip install RPi.GPIO mfrc522

# Face recognition (takes ~30 min on Pi to compile dlib)
pip install face_recognition
```

> **Note:** If `dlib` compilation fails due to memory, add swap:
> ```bash
> sudo dphys-swapfile swapoff
> sudo sed -i 's/CONF_SWAPSIZE=.*/CONF_SWAPSIZE=2048/' /etc/dphys-swapfile
> sudo dphys-swapfile setup
> sudo dphys-swapfile swapon
> ```

---

## Step 4: Configure Backend Connection

Edit `main.py` and update `base_url` to point to your ASP.NET server:

```python
# In main() function at bottom of main.py:
system = SmartSecuritySystem(
    use_simulated_rfid=False,  # Auto-detected on Pi
    base_url="http://192.168.1.100:5000",  # ← Your ASP.NET server IP
    camera_id=1,
    room_id=1,
    max_stay_minutes=20,
    room_max_capacity=10,
    operating_hours_start=6,
    operating_hours_end=22
)
```

---

## Step 5: Test Components Individually

```bash
cd /home/pi/SmartSecuritySystem/IotController
source ../venv/bin/activate

# Test camera
python -c "from Sensors.camera_module import CameraModule; c = CameraModule(); print(c.initialize())"

# Test PIR sensor
python -c "from Sensors.pir_sensor import PIRSensor; p = PIRSensor(); p.initialize(); print('PIR OK')"

# Test RFID reader
python -c "from Sensors.rfid_reader import RFIDReader; r = RFIDReader(); r.start_reading(); import time; time.sleep(10)"

# Test buzzer
python -c "from Sensors.hardware import Buzzer; b = Buzzer(); b.initialize(); b.beep(1); import time; time.sleep(2); b.cleanup()"

# Test RGB LED
python -c "from Sensors.hardware import RGBLed; l = RGBLed(); l.initialize(); l.status_idle(); import time; time.sleep(3); l.cleanup()"

# Test door sensor
python -c "from Sensors.hardware import DoorSensor; d = DoorSensor(); d.initialize(); print('Door:', 'OPEN' if d.is_door_open() else 'CLOSED')"

# Test solenoid lock
python -c "from Sensors.lock_sensor import SolenoidLock; s = SolenoidLock(); s.initialize(); s.unlock(3); import time; time.sleep(5); s.cleanup()"
```

---

## Step 6: Run Full System (Manual Test)

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
[ALARM] Settings synced: {'intrusion': True, 'fire': True, ...}

==================================================
 FSM Security System Running [RASPBERRY PI]
 Press Ctrl+C to stop
==================================================
```

---

## Step 7: Install as systemd Service (Auto-Start)

```bash
# Copy service file
sudo cp /home/pi/SmartSecuritySystem/IotController/deploy/smartsecurity.service \
        /etc/systemd/system/smartsecurity.service

# Reload systemd
sudo systemctl daemon-reload

# Enable auto-start on boot
sudo systemctl enable smartsecurity

# Start the service
sudo systemctl start smartsecurity

# Check status
sudo systemctl status smartsecurity

# View logs
journalctl -u smartsecurity -f
```

### Service Management Commands

```bash
sudo systemctl start smartsecurity     # Start
sudo systemctl stop smartsecurity      # Stop
sudo systemctl restart smartsecurity   # Restart
sudo systemctl status smartsecurity    # Status
journalctl -u smartsecurity --since today  # Today's logs
```

---

## GPIO Wiring Diagram

```
┌─────────────────────────────────────────────────────────┐
│                   RASPBERRY PI 5 GPIO                    │
│                                                          │
│  BCM Pin  │  Physical Pin  │  Component     │  Notes     │
│───────────┼────────────────┼────────────────┼────────────│
│  GPIO 17  │  Pin 11        │  PIR HC-SR501  │  INPUT     │
│  GPIO 18  │  Pin 12        │  Relay Module  │  OUTPUT    │
│  GPIO 24  │  Pin 18        │  Active Buzzer │  OUTPUT    │
│  GPIO 5   │  Pin 29        │  RGB LED (R)   │  + 220Ω   │
│  GPIO 6   │  Pin 31        │  RGB LED (G)   │  + 220Ω   │
│  GPIO 13  │  Pin 33        │  RGB LED (B)   │  + 220Ω   │
│  GPIO 16  │  Pin 36        │  Door Sensor   │  PULL_UP  │
│  GPIO 8   │  Pin 24 (CE0)  │  RFID SDA      │  SPI      │
│  GPIO 11  │  Pin 23        │  RFID SCK      │  SPI      │
│  GPIO 10  │  Pin 19        │  RFID MOSI     │  SPI      │
│  GPIO 9   │  Pin 21        │  RFID MISO     │  SPI      │
│  GPIO 25  │  Pin 22        │  RFID RST      │  OUTPUT   │
│  3.3V     │  Pin 1         │  RFID VCC      │  Power    │
│  GND      │  Pin 6,9,etc   │  Common Ground │  Ground   │
│  CSI      │  Ribbon        │  Camera Mod 3  │  CSI Port │
└─────────────────────────────────────────────────────────┘
```

### Solenoid Lock Wiring (IMPORTANT)

```
              ┌──────────────┐
GPIO 18 ──→──│ IN   Relay   │──→── 12V Solenoid Lock
  3.3V  ──→──│ VCC  Module  │      (NO + COM terminals)
  GND   ──→──│ GND          │
              └──────────────┘
              12V PSU ──→── Relay COM terminal
```

> ⚠️ **NEVER** connect 12V directly to GPIO pins. Always use a relay module.

### Door Sensor Wiring

```
GPIO 16 ──→── Reed Switch ──→── GND
(internal pull-up enabled in software)
```

---

## Troubleshooting

### Camera not detected
```bash
# Check if libcamera works
libcamera-hello --timeout 3000

# Check V4L2 devices
ls -la /dev/video*

# Enable camera in config
sudo raspi-config   # Interface Options → Camera
```

### RFID not reading
```bash
# Check SPI is enabled
ls /dev/spi*
# Should show: /dev/spidev0.0  /dev/spidev0.1

# Check SPI module loaded
lsmod | grep spi
```

### Permission errors
```bash
sudo usermod -aG gpio,spi,i2c,video pi
sudo reboot
```

### Service won't start
```bash
# Check logs for errors
journalctl -u smartsecurity -n 50 --no-pager

# Test manually first
cd /home/pi/SmartSecuritySystem/IotController
../venv/bin/python main.py
```
