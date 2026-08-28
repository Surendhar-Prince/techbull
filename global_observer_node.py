"""
Global Observer Node (Laptop 1)
Passive dashboard and Genesis Task Injector (Log-based UI for stability).
"""

import socket
import json
import time
import threading
from core.data_schemas import GenesisTaskPacket, Task

class GlobalMonitor:
    def __init__(self):
        self.amr_states = {}
        self.udp_port = 5005
        
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.bind(("", self.udp_port))
        self.running = True

    def listen_to_mesh(self):
        """Continuously captures state broadcasts and prints updates cleanly."""
        print("=========================================================")
        print(" 🏢 SIH 26123 DECENTRALIZED FLEET MONITOR (LAP_MAP)")
        print("=========================================================\n")
        print("⏳ Listening for AMR broadcasts on UDP port 5005...\n")
        
        while self.running:
            try:
                data, addr = self.sock.recvfrom(4096)
                payload = json.loads(data.decode("utf-8"))
                if payload.get("packet_type") == "STATE_INTENT":
                    amr_id = payload["amr_id"]
                    # Only print if state changed or periodically to avoid spamming, 
                    # or print clean telemetry lines:
                    self.amr_states[amr_id] = payload
            except Exception:
                pass

    def input_listener(self):
        """Stable, non-flickering prompt handler for injecting tasks."""
        while self.running:
            try:
                cmd = input("Command [Type 'task' to inject orders]: ")
                if cmd.strip().lower() == "task":
                    t1 = Task(task_id="T_01", pickup_node="N_07", dropoff_node="N_13")
                    t2 = Task(task_id="T_02", pickup_node="N_09", dropoff_node="N_15")
                    
                    pkt = GenesisTaskPacket(tasks=[t1, t2])
                    self.sock.sendto(pkt.to_bytes(), ("255.255.255.255", self.udp_port))
                    print(f"\n📡 [LAP_MAP] Genesis Packet Broadcasted Successfully: T_01, T_02\n")
            except (EOFError, KeyboardInterrupt):
                break

    def status_printer(self):
        """Prints a clean summary every 3 seconds instead of pulsing every 0.5 seconds."""
        while self.running:
            time.sleep(3.0)
            if self.amr_states:
                print("\n--- [FLEET STATUS SNAPSHOT] ---")
                current_time = time.time()
                for amr_id, state in sorted(self.amr_states.items()):
                    age = current_time - state["timestamp"]
                    status = "ONLINE" if age < 2.0 else "GHOST"
                    print(f"[{status}] {amr_id} | State: {state['fsm_state']} | Node: {state['current_node']} -> {state['target_node']} | Battery: {state['battery']}%")
                print("-------------------------------\n")

if __name__ == "__main__":
    monitor = GlobalMonitor()
    
    # Start threads
    threading.Thread(target=monitor.listen_to_mesh, daemon=True).start()
    threading.Thread(target=monitor.status_printer, daemon=True).start()
    
    try:
        # Run the clean input prompt in the main thread
        monitor.input_listener()
    except KeyboardInterrupt:
        monitor.running = False
        print("\nExiting Global Observer...")