import serial
import threading
import time

class RFIDReader:
    """Reads RFID data from serial device"""
    
    def __init__(self, port='COM3', baudrate=9600, timeout=1):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None
        self.is_reading = False
        self.last_rfid = None
        self.rfid_callback = None
        self.lock = threading.Lock()
    
    def connect(self):
        """Connect to RFID reader serial port"""
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout
            )
            print(f"Connected to RFID reader on {self.port}")
            return True
        except Exception as e:
            print(f"Failed to connect to RFID reader: {e}")
            return False
    
    def start_reading(self, callback=None):
        """
        Start reading RFID data in background thread
        
        Args:
            callback: Function to call when RFID is read. Signature: callback(user_id)
        """
        if not self.ser or not self.ser.is_open:
            print("RFID reader not connected")
            return False
        
        if self.is_reading:
            return True
        
        self.rfid_callback = callback
        self.is_reading = True
        read_thread = threading.Thread(target=self._read_loop, daemon=True)
        read_thread.start()
        return True
    
    def _read_loop(self):
        """Continuous RFID reading loop"""
        while self.is_reading:
            try:
                if self.ser.in_waiting:
                    data = self.ser.readline().decode('utf-8').strip()
                    
                    if data:
                        # Extract RFID (assuming format like "USER123" or decimal ID)
                        rfid_data = data.upper()
                        
                        with self.lock:
                            self.last_rfid = rfid_data
                        
                        print(f"RFID Read: {rfid_data}")
                        
                        # Call callback if registered
                        if self.rfid_callback:
                            self.rfid_callback(rfid_data)
                else:
                    time.sleep(0.1)
            except Exception as e:
                print(f"RFID read error: {e}")
                time.sleep(0.1)
    
    def get_last_rfid(self):
        """Get the last read RFID value"""
        with self.lock:
            return self.last_rfid
    
    def stop_reading(self):
        """Stop RFID reading"""
        self.is_reading = False
    
    def disconnect(self):
        """Disconnect from RFID reader"""
        self.is_reading = False
        if self.ser and self.ser.is_open:
            self.ser.close()
            print("RFID reader disconnected")
    
    def simulate_rfid(self, user_id):
        """
        Simulate RFID read (for testing without hardware)
        
        Args:
            user_id: User ID to simulate
        """
        with self.lock:
            self.last_rfid = user_id
        
        print(f"[SIMULATED] RFID Read: {user_id}")
        
        if self.rfid_callback:
            self.rfid_callback(user_id)
