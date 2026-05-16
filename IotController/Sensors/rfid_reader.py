"""
RC522 RFID Reader — Pure SPI, No RPi.GPIO Dependency

Production-grade RFID reader using raw SPI register access via spidev.
No RPi.GPIO, no mfrc522 library — direct RC522 communication only.
Works on Raspberry Pi 5 (Debian Trixie) without GPIO compatibility shims.

Architecture:
- ISO 14443A Type A card detection (REQA → Anticollision → Select)
- Raw SPI register read/write via spidev (bus 0, CE0)
- Per-UID debounce to prevent duplicate callbacks
- Thread-safe, non-blocking polling loop
- Simulation fallback for laptop/desktop testing

GPIO (SPI0):
    SDA:   GPIO 8  (CE0) — Pin 24
    SCK:   GPIO 11       — Pin 23
    MOSI:  GPIO 10       — Pin 19
    MISO:  GPIO 9        — Pin 21
    RST:   GPIO 25       — Pin 22  (directly wired HIGH — no GPIO control needed)
    3.3V:                — Pin 1
    GND:                 — Pin 6

Dependencies:
    - spidev==3.6  (SPI bus access — kernel-level, no GPIO needed)
"""

import time
import threading
import platform


class RFIDReader:
    """
    RC522 RFID Reader (Pure SPI — No RPi.GPIO)

    Communicates directly with the MFRC522 chip via SPI registers.
    RST pin is hardwired HIGH (always active) — no GPIO pin control needed.

    Public API:
        start_reading(callback)  — Start RFID scanning loop
        simulate_tap(uid)        — Queue a simulated card tap
        get_last_rfid()          — Get last scanned UID
        stop_reading()           — Stop the scanning loop
        cleanup()                — Release hardware resources
    """

    # ===========================
    # RC522 REGISTER MAP
    # ===========================
    COMMAND_REG     = 0x01
    COM_IRQ_REG     = 0x04
    ERROR_REG       = 0x06
    FIFO_DATA_REG   = 0x09
    FIFO_LEVEL_REG  = 0x0A
    CONTROL_REG     = 0x0C
    BIT_FRAMING_REG = 0x0D
    COLL_REG        = 0x0E
    MODE_REG        = 0x11
    TX_MODE_REG     = 0x12
    RX_MODE_REG     = 0x13
    TX_CONTROL_REG  = 0x14
    TX_ASK_REG      = 0x15
    TIMER_MODE_REG  = 0x2A
    TIMER_PRESCALER = 0x2B
    TIMER_RELOAD_H  = 0x2C
    TIMER_RELOAD_L  = 0x2D
    VERSION_REG     = 0x37

    # RC522 Commands
    CMD_IDLE        = 0x00
    CMD_TRANSCEIVE  = 0x0C
    CMD_SOFTRESET   = 0x0F

    # ISO 14443A Commands
    PICC_REQA       = 0x26
    PICC_ANTICOLL   = 0x93

    def __init__(self, simulated=None, debounce_seconds=3.0):
        """
        Args:
            simulated:        Force simulation mode. None = auto-detect.
            debounce_seconds: Min seconds between callbacks for the SAME UID.
        """
        self.is_reading = False
        self.rfid_callback = None
        self.last_rfid = None
        self.lock = threading.Lock()

        # Debounce
        self._debounce_seconds = debounce_seconds
        self._last_uid = None
        self._last_time = 0.0

        # Platform detection
        if simulated is None:
            self.simulated = platform.system().lower() != "linux"
        else:
            self.simulated = simulated

        # Simulation queue
        self._sim_queue = []
        self._sim_lock = threading.Lock()

        # SPI handle
        self.spi = None

    # ===========================
    # SPI LOW-LEVEL I/O
    # ===========================
    def _write(self, addr, val):
        """Write a single byte to an RC522 register via SPI."""
        self.spi.xfer2([(addr << 1) & 0x7E, val])

    def _read(self, addr):
        """Read a single byte from an RC522 register via SPI."""
        return self.spi.xfer2([((addr << 1) & 0x7E) | 0x80, 0])[1]

    def _set_bitmask(self, addr, mask):
        """Set specific bits in a register."""
        val = self._read(addr)
        self._write(addr, val | mask)

    def _clear_bitmask(self, addr, mask):
        """Clear specific bits in a register."""
        val = self._read(addr)
        self._write(addr, val & (~mask))

    # ===========================
    # RC522 HARDWARE INIT
    # ===========================
    def _init_hardware(self):
        """Initialize RC522 via SPI. No GPIO pins used."""
        try:
            import spidev
            self.spi = spidev.SpiDev()
            self.spi.open(0, 0)           # SPI bus 0, CE0 (GPIO 8)
            self.spi.max_speed_hz = 1000000
            self.spi.mode = 0

            # Soft reset
            self._write(self.COMMAND_REG, self.CMD_SOFTRESET)
            time.sleep(0.05)

            # Timer: auto-start, prescaler for ~25ms timeout
            self._write(self.TIMER_MODE_REG, 0x8D)   # TAuto=1, TPrescaler_Hi
            self._write(self.TIMER_PRESCALER, 0x3E)   # TPrescaler_Lo
            self._write(self.TIMER_RELOAD_H, 0x00)    # Reload value high
            self._write(self.TIMER_RELOAD_L, 0x1E)    # Reload value low (30)

            # Force 100% ASK modulation
            self._write(self.TX_ASK_REG, 0x40)

            # CRC preset 6363h (ISO 14443A standard)
            self._write(self.MODE_REG, 0x3D)

            # Enable antenna (TX1 + TX2 RF driver)
            self._set_bitmask(self.TX_CONTROL_REG, 0x03)

            # Verify chip responds
            version = self._read(self.VERSION_REG)
            if version == 0x00 or version == 0xFF:
                print("[RFID ERROR] RC522 not responding (bad version byte)")
                return False

            chip = {0x91: "v1.0", 0x92: "v2.0", 0x88: "clone"}.get(version, f"0x{version:02X}")
            print(f"[RFID] RC522 initialized via SPI (chip {chip})")
            return True

        except ImportError:
            print("[RFID ERROR] spidev not installed. Install: pip install spidev")
            return False
        except FileNotFoundError:
            print("[RFID ERROR] SPI device /dev/spidev0.0 not found. Enable SPI via raspi-config")
            return False
        except Exception as e:
            print(f"[RFID ERROR] SPI init failed: {e}")
            return False

    # ===========================
    # ISO 14443A CARD COMMUNICATION
    # ===========================
    def _transceive(self, data):
        """
        Send data to a card and receive the response.

        Handles the full MFRC522 FIFO + IRQ flow:
        1. Flush FIFO
        2. Load data into FIFO
        3. Execute Transceive command
        4. Wait for response or timeout
        5. Read response from FIFO

        Returns:
            (status, response_bytes) — status True if card responded
        """
        self._write(self.COMMAND_REG, self.CMD_IDLE)
        self._write(self.COM_IRQ_REG, 0x7F)        # Clear all IRQ flags
        self._set_bitmask(self.FIFO_LEVEL_REG, 0x80)  # Flush FIFO

        # Write data to FIFO
        for byte in data:
            self._write(self.FIFO_DATA_REG, byte)

        # Execute Transceive
        self._write(self.COMMAND_REG, self.CMD_TRANSCEIVE)
        self._set_bitmask(self.BIT_FRAMING_REG, 0x80)  # StartSend

        # Wait for completion (RxIRq or TimerIRq)
        timeout_counter = 2000
        while timeout_counter > 0:
            irq = self._read(self.COM_IRQ_REG)
            if irq & 0x30:  # RxIRq (0x20) or IdleIRq (0x10)
                break
            if irq & 0x01:  # TimerIRq — timeout
                return False, []
            timeout_counter -= 1

        if timeout_counter == 0:
            return False, []

        # Check for errors
        error = self._read(self.ERROR_REG)
        if error & 0x1B:  # BufferOvfl, CollErr, ParityErr, ProtocolErr
            return False, []

        # Read FIFO
        n = self._read(self.FIFO_LEVEL_REG)
        result = []
        for _ in range(n):
            result.append(self._read(self.FIFO_DATA_REG))

        return True, result

    def _request_card(self):
        """Send REQA (Request Type A) to detect nearby cards."""
        self._write(self.BIT_FRAMING_REG, 0x07)  # 7 bits for REQA
        status, _ = self._transceive([self.PICC_REQA])
        self._write(self.BIT_FRAMING_REG, 0x00)  # Reset framing
        return status

    def _anticollision(self):
        """
        Run anticollision loop to get the card's 4-byte UID.

        Returns:
            UID hex string (e.g., "A1B2C3D4") or None
        """
        self._write(self.BIT_FRAMING_REG, 0x00)
        status, data = self._transceive([self.PICC_ANTICOLL, 0x20])

        if not status or len(data) < 5:
            return None

        # Verify BCC (Block Check Character) — XOR of UID bytes
        uid_bytes = data[:4]
        bcc = data[4]
        if (uid_bytes[0] ^ uid_bytes[1] ^ uid_bytes[2] ^ uid_bytes[3]) != bcc:
            return None

        # Convert to uppercase hex string
        return ''.join(f'{b:02X}' for b in uid_bytes)

    def _read_card(self):
        """
        Attempt to read a card UID. Non-blocking.

        Returns:
            UID string or None if no card present.
        """
        if not self._request_card():
            return None

        return self._anticollision()

    # ===========================
    # START
    # ===========================
    def start_reading(self, callback=None):
        """
        Start RFID scanning loop.

        callback: function(uid: str) — called for every unique card tap
        """
        self.rfid_callback = callback
        self.is_reading = True

        if not self.simulated:
            if not self._init_hardware():
                print("[RFID] Falling back to SIMULATED mode")
                self.simulated = True

        thread = threading.Thread(target=self._loop, daemon=True)
        thread.start()

        mode = "SIMULATED" if self.simulated else "RC522 SPI"
        print(f"[RFID] Reader started ({mode})")
        return True

    # ===========================
    # MAIN LOOP
    # ===========================
    def _loop(self):
        """Non-blocking polling loop. Runs in daemon thread."""
        while self.is_reading:
            try:
                if self.simulated:
                    uid = None
                    with self._sim_lock:
                        if self._sim_queue:
                            uid = self._sim_queue.pop(0)

                    if uid:
                        self._handle(uid)

                    time.sleep(0.5)
                else:
                    uid = self._read_card()

                    if uid:
                        self._handle(uid)

                    time.sleep(0.2)

            except Exception as e:
                print(f"[RFID ERROR] {e}")
                time.sleep(1)

    # ===========================
    # HANDLE CARD (ALL CARDS — known or unknown)
    # ===========================
    def _handle(self, uid):
        """
        Process any RFID card tap — known or unknown.

        Per-UID debounce prevents duplicate callbacks when a card
        is held against the reader or tapped rapidly.
        Different UIDs are tracked independently.
        """
        now = time.time()

        # Per-UID debounce
        if uid == self._last_uid and (now - self._last_time) < self._debounce_seconds:
            return

        self._last_uid = uid
        self._last_time = now

        # Thread-safe last RFID storage
        with self.lock:
            self.last_rfid = uid

        print(f"[RFID] Card detected UID: {uid}")

        if self.rfid_callback:
            self.rfid_callback(uid)

    # ===========================
    # SIMULATION
    # ===========================
    def simulate_tap(self, uid):
        """Queue a simulated RFID tap for testing."""
        if not self.simulated:
            print("[RFID] Cannot simulate on hardware mode")
            return

        with self._sim_lock:
            self._sim_queue.append(str(uid))

        print(f"[RFID SIM] Card queued: {uid}")

    # ===========================
    # GET LAST RFID
    # ===========================
    def get_last_rfid(self):
        """Return the last scanned UID (thread-safe)."""
        with self.lock:
            return self.last_rfid

    # ===========================
    # STOP
    # ===========================
    def stop_reading(self):
        """Stop the scanning loop."""
        self.is_reading = False
        print("[RFID] Stopped reading")

    # ===========================
    # CLEANUP
    # ===========================
    def cleanup(self):
        """Release SPI hardware resources. Safe to call multiple times."""
        self.is_reading = False

        if self.spi:
            try:
                # Disable antenna before closing
                self._clear_bitmask(self.TX_CONTROL_REG, 0x03)
                self.spi.close()
                self.spi = None
            except Exception as e:
                print(f"[RFID] Cleanup error: {e}")

        print("[RFID] Cleaned up")