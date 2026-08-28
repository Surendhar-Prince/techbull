"""
AMR Parasite Node (Edge Controller)
Main executable for Laptops 2-5. Manages FSM, UDP Networking, and Hardware.
"""

import time
import socket
import threading
import json
import math
import networkx as nx

from core.data_schemas import StateIntentPacket, Task, calculate_task_pool_hash
from core.host_hardware_bridge import HostHardwareBridge
from algorithms.path_planner import NetworkXPlanner
from algorithms.cbba_solver import CBBAConsensus

class ParasiteEdgeNode:
    def __init__(self, amr_id: str, start_node: str):
        self.amr_id = amr_id
        self.current_node = start_node
        self.target_node = ""
        self.battery = 100.0
        self.wait_time_sec = 0.0
        
        # Modules
        self.planner = NetworkXPlanner("configs/warehouse_map.json")
        self.hardware = HostHardwareBridge(amr_id)
        self.cbba = CBBAConsensus(amr_id)
        
        # FSM and State Data
        self.fsm_state = "IDLE"
        self.planned_path = []
        self.claimed_mutex = []
        self.peer_registry = {}  
        self.active_tasks_dict = {}  # Safely stores the actual Task objects
        
        # Network Setup
        self.udp_port = 5005
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.bind(("", self.udp_port))
        
        # Start Background Listener
        threading.Thread(target=self.udp_listener, daemon=True).start()

    def udp_listener(self):
        """Background thread handling inbound UDP traffic."""
        while True:
            try:
                data, addr = self.sock.recvfrom(4096)
                payload = json.loads(data.decode("utf-8"))
                
                # 1. Handle Genesis Task Injection
                if payload.get("packet_type") == "GENESIS_TASK":
                    print(f"\n[{self.amr_id}] 📥 Received Genesis Tasks!")
                    for t_data in payload.get("tasks", []):
                        task = Task.from_dict(t_data)
                        self.active_tasks_dict[task.task_id] = task
                        self.cbba.winning_bids[task.task_id] = {"winning_amr": "NONE", "bid_cost": 9999.0}
                    continue
                
                # 2. Handle Peer State Intents
                if payload.get("packet_type") == "STATE_INTENT" and payload["amr_id"] != self.amr_id:
                    peer_pkt = StateIntentPacket.from_dict(payload)
                    
                    # Spatial Scoping Fix
                    my_x, my_y = self.planner.get_node_coordinates(self.current_node)
                    peer_x, peer_y = self.planner.get_node_coordinates(peer_pkt.current_node)
                    if math.hypot(peer_x - my_x, peer_y - my_y) > .0:
                        continue 
                        
                    self.peer_registry[peer_pkt.amr_id] = peer_pkt
                    
            except Exception:
                pass 

    def broadcast_state(self):
        """Fires the local state to the UDP mesh."""
        pkt = StateIntentPacket(
            amr_id=self.amr_id,
            timestamp=time.time(),
            current_node=self.current_node,
            target_node=self.target_node,
            planned_path=self.planned_path,
            claimed_mutex=self.claimed_mutex,
            battery=self.battery,
            payload_status="EMPTY",
            wait_time_sec=self.wait_time_sec,
            fsm_state=self.fsm_state,
            active_task_id=self.cbba.local_bundle[0] if self.cbba.local_bundle else None,
            task_pool_hash=calculate_task_pool_hash(self.cbba.winning_bids),
            task_bundle=self.cbba.get_current_bids_for_broadcast()
        )
        self.sock.sendto(pkt.to_bytes(), ("255.255.255.255", self.udp_port))

    def run_fsm(self):
        """Main execution loop running at 10 Hz."""
        print(f"[{self.amr_id}] 🚀 Edge Controller Online. FSM Started.")
        
        while True:
            # 1. Ghost Protocol Cleanup
            current_time = time.time()
            ghosts = [p_id for p_id, p_state in self.peer_registry.items() if current_time - p_state.timestamp > 2.0]
            for g in ghosts:
                print(f"[{self.amr_id}] 👻 Peer {g} lost! Dropping their constraints.")
                del self.peer_registry[g]

            # 2. Update dynamic network map weights
            active_claims = []
            for p_state in self.peer_registry.values():
                if len(p_state.claimed_mutex) >= 2:
                    active_claims.append((p_state.claimed_mutex[0], p_state.claimed_mutex[1]))
            self.planner.apply_peer_mutexes(active_claims)

            # ==========================================
            # 3. CORE STATE MACHINE LOGIC
            # ==========================================
            if self.fsm_state == "IDLE":
                unassigned_tasks = list(self.active_tasks_dict.values())
                
                if unassigned_tasks:
                    # Run the Auction!
                    self.cbba.build_local_bundle(unassigned_tasks, self.current_node, self.peer_registry, self.planner, is_idle=True)
                    self.cbba.update_bids(self.peer_registry)

                    # Check if we won the bid consensus
                    if self.cbba.local_bundle:
                        won_id = self.cbba.local_bundle[0]
                        record = self.cbba.winning_bids.get(won_id)
                        
                        if record and record["winning_amr"] == self.amr_id:
                            self.target_node = self.active_tasks_dict[won_id].pickup_node
                            print(f"\n[{self.amr_id}] 🏆 Won auction for {won_id}! Target: {self.target_node}")
                            self.fsm_state = "PLANNING"
                            
            elif self.fsm_state == "PLANNING":
                try:
                    self.planned_path = self.planner.compute_safe_path(self.current_node, self.target_node)
                    self.claimed_mutex = self.planned_path[:2] 
                    print(f"[{self.amr_id}] 🗺️ Path Calculated: {self.planned_path}")
                    self.fsm_state = "NAVIGATING"
                except nx.NetworkXNoPath:
                    self.fsm_state = "YIELDING" 

            elif self.fsm_state == "NAVIGATING":
                if len(self.planned_path) > 1:
                    next_node = self.planned_path[1]
                    tx, ty = self.planner.get_node_coordinates(next_node)
                    
                    # Fire physical hardware command
                    self.hardware.send_drive_command(next_node, tx, ty)
                    
                    # Simulate driving time (Wait 1.5s between nodes)
                    time.sleep(1.5) 
                    
                    # Update local state after arriving at node
                    self.current_node = next_node
                    self.planned_path.pop(0)
                    self.claimed_mutex = self.planned_path[:2]
                else:
                    print(f"\n[{self.amr_id}] ✅ Arrived at {self.target_node}. Task Completed!")
                    
                    # Clean up memory
                    if self.cbba.local_bundle:
                        completed_id = self.cbba.local_bundle.pop(0)
                        del self.cbba.winning_bids[completed_id]
                        del self.active_tasks_dict[completed_id]
                        
                    self.fsm_state = "IDLE" 

            elif self.fsm_state == "YIELDING":
                self.hardware.send_stop_command("WAITING_FOR_PEER")
                self.wait_time_sec += 0.1 
                self.fsm_state = "PLANNING" 

            # Broadcast state & maintain loop speed
            self.broadcast_state()
            time.sleep(0.1)

if __name__ == "__main__":
    node = ParasiteEdgeNode(amr_id="AMR_3", start_node="N_03")
    node.run_fsm()