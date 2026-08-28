"""
Host Hardware Bridge (The Parasite Interface).
Translates high-level FSM decisions into mocked UART/Serial commands 
for the locked host AMR firmware.
"""

import time

class HostHardwareBridge:
    def __init__(self, amr_id: str, port: str = "/dev/ttyUSB0", baudrate: int = 115200):
        self.amr_id = amr_id
        self.port = port
        self.baudrate = baudrate
        self.is_connected = False
        self._connect_to_host()

    def _connect_to_host(self):
        """Mocks opening a serial connection to the proprietary host hardware."""
        # In production: self.serial = serial.Serial(self.port, self.baudrate)
        print(f"[{self.amr_id} HARDWARE] 🔌 Opening serial connection on {self.port} at {self.baudrate} baud...")
        time.sleep(0.5)
        self.is_connected = True
        print(f"[{self.amr_id} HARDWARE] ✅ Successfully bound to Host AMR firmware.")

    def send_drive_command(self, target_node_id: str, x: float, y: float):
        """
        Commands the host AMR to drive to a specific topological coordinate.
        """
        if not self.is_connected:
            return
            
        payload = f"$CMD,DRIVE,{target_node_id},{x:.2f},{y:.2f},*FF\n"
        print(f"[{self.amr_id} UART_TX] ➔ {payload.strip()}")
        # In production: self.serial.write(payload.encode('utf-8'))

    def send_stop_command(self, reason: str = "YIELDING"):
        """
        Issues an immediate software brake command to the host AMR.
        """
        payload = f"$CMD,STOP,{reason},*FF\n"
        print(f"[{self.amr_id} UART_TX] 🛑 ➔ {payload.strip()}")

    def send_reverse_command(self, spur_node_id: str, x: float, y: float):
        """
        Commands the host AMR to execute an emergency reverse maneuver 
        to clear a 1-lane choke point.
        """
        payload = f"$CMD,REVERSE,{spur_node_id},{x:.2f},{y:.2f},*FF\n"
        print(f"[{self.amr_id} UART_TX] ⚠️ ➔ {payload.strip()}")