"""
Consensus-Based Bundle Algorithm (CBBA) Solver.
Handles decentralized task bidding, congestion-aware cost calculation, 
and peer-to-peer consensus updating.
"""

from typing import Dict, List, Any

class CBBAConsensus:
    def __init__(self, amr_id: str):
        self.amr_id = amr_id
        # Tracks the global state of bids: {task_id: {"winning_amr": str, "bid_cost": float}}
        self.winning_bids: Dict[str, Dict[str, Any]] = {}  
        # Tracks tasks officially claimed by THIS robot
        self.local_bundle: List[str] = []  

    def calculate_bid(self, task, current_node: str, peer_registry: Dict, planner, is_idle: bool) -> float:
        """
        Calculates the insertion cost for a task. 
        In our system, lower cost is better.
        """
        # 1. Base Graph Distance
        try:
            # We use the Euclidean heuristic for rapid bidding rather than a full A* search
            base_distance = planner._astar_heuristic(current_node, task.pickup_node)
        except KeyError:
            # Node not found in graph, return massive cost
            return 99999.0

        # 2. Congestion Penalty 
        # Evaluate how many active peers are currently heading toward the task's zone
        congestion_count = 0
        for peer_id, peer_state in peer_registry.items():
            if task.pickup_node in peer_state.planned_path or task.pickup_node in peer_state.claimed_mutex:
                congestion_count += 1
        
        weight_congestion = 15.0 # Configurable penalty multiplier
        bid_cost = base_distance + (weight_congestion * congestion_count)

        # 3. Cooperative Pooling (Idle Discount)
        # Force idle AMRs to grab tasks rather than letting busy AMRs hoard them
        if is_idle:
            bid_cost *= 0.5 

        # 4. Urgency Priority
        # A higher urgency (e.g., 2.0) drastically lowers the bid cost, prioritizing the task
        if hasattr(task, 'urgency') and task.urgency > 0:
            bid_cost /= float(task.urgency)

        return round(bid_cost, 2)

    def build_local_bundle(self, unassigned_tasks: List, current_node: str, peer_registry: Dict, planner, is_idle: bool):
        """
        Evaluates the pool of unassigned tasks and actively bids on them.
        """
        for task in unassigned_tasks:
            bid_cost = self.calculate_bid(task, current_node, peer_registry, planner, is_idle)
            
            local_record = self.winning_bids.get(task.task_id)
            
            # If the task is totally new OR our new bid is better than the current winning bid
            if not local_record or bid_cost < local_record["bid_cost"]:
                self.winning_bids[task.task_id] = {
                    "winning_amr": self.amr_id, 
                    "bid_cost": bid_cost
                }
                if task.task_id not in self.local_bundle:
                    self.local_bundle.append(task.task_id)

    def update_bids(self, peer_registry: Dict) -> bool:
        """
        The Core Consensus Phase.
        Compares local winning_bids against the task bundles broadcasted by peers.
        Resolves conflicts by conceding tasks to the AMR with the absolute lowest cost.
        Returns True if consensus is reached (no changes made), False if bids were updated.
        """
        consensus_reached = True
        
        for peer_id, peer_state in peer_registry.items():
            # Peer's local bundle should be passed in the state intent packet
            # Expected format: {task_id: peer_bid_cost}
            peer_bundle = getattr(peer_state, 'task_bundle', {})
            
            for task_id, peer_cost in peer_bundle.items():
                local_record = self.winning_bids.get(task_id)
                
                # Condition A: We don't know about this task (discovered via Gossip)
                if not local_record:
                    self.winning_bids[task_id] = {"winning_amr": peer_id, "bid_cost": peer_cost}
                    consensus_reached = False
                
                # Condition B: The Peer outbid us (they have a lower cost)
                elif peer_cost < local_record["bid_cost"]:
                    self.winning_bids[task_id] = {"winning_amr": peer_id, "bid_cost": peer_cost}
                    if task_id in self.local_bundle:
                        self.local_bundle.remove(task_id) # Drop the task, we lost the auction
                    consensus_reached = False
                    
                # Condition C: Exact Tie. Use MAC/AMR ID string comparison to resolve.
                elif peer_cost == local_record["bid_cost"] and peer_id != local_record["winning_amr"]:
                    # Lexicographical comparison (AMR_1 beats AMR_2)
                    if peer_id < local_record["winning_amr"]:
                        self.winning_bids[task_id] = {"winning_amr": peer_id, "bid_cost": peer_cost}
                        if task_id in self.local_bundle:
                            self.local_bundle.remove(task_id)
                        consensus_reached = False
        
        return consensus_reached

    def get_current_bids_for_broadcast(self) -> Dict[str, float]:
        """
        Extracts the AMR's current local bundle and exact bid costs to package 
        into the 10 Hz UDP StateIntentPacket.
        """
        broadcast_bundle = {}
        for task_id in self.local_bundle:
            record = self.winning_bids.get(task_id)
            if record:
                broadcast_bundle[task_id] = record["bid_cost"]
        return broadcast_bundle


# ==========================================
# Quick Sanity Test
# ==========================================
if __name__ == "__main__":
    from types import SimpleNamespace

    print("--- Testing CBBA Consensus Solver ---")
    
    # Mocking a Planner and Task for the test
    class MockPlanner:
        def _astar_heuristic(self, n1, n2): return 25.0 # Mock distance

    mock_task = SimpleNamespace(task_id="T_01", pickup_node="N_08", dropoff_node="N_15", urgency=1.0)
    
    # Initialize AMR 1 and AMR 2
    amr1_cbba = CBBAConsensus(amr_id="AMR_1")
    amr2_cbba = CBBAConsensus(amr_id="AMR_2")

    # AMR 1 bids while IDLE (Gets a massive cost discount)
    amr1_cbba.build_local_bundle([mock_task], "N_01", {}, MockPlanner(), is_idle=True)
    print(f"AMR 1 (IDLE) bids on T_01: {amr1_cbba.winning_bids['T_01']['bid_cost']}")

    # AMR 2 bids while BUSY (No discount)
    amr2_cbba.build_local_bundle([mock_task], "N_02", {}, MockPlanner(), is_idle=False)
    print(f"AMR 2 (BUSY) bids on T_01: {amr2_cbba.winning_bids['T_01']['bid_cost']}")

    # Simulate UDP Broadcast: AMR 1 receives AMR 2's packet, AMR 2 receives AMR 1's packet
    amr1_mock_packet = SimpleNamespace(task_bundle=amr1_cbba.get_current_bids_for_broadcast())
    amr2_mock_packet = SimpleNamespace(task_bundle=amr2_cbba.get_current_bids_for_broadcast())

    # Update Consensuses
    amr1_cbba.update_bids({"AMR_2": amr2_mock_packet})
    amr2_cbba.update_bids({"AMR_1": amr1_mock_packet})

    # The result should be universally agreed upon without a server
    print(f"AMR 1 Local Consensus Winner: {amr1_cbba.winning_bids['T_01']['winning_amr']}")
    print(f"AMR 2 Local Consensus Winner: {amr2_cbba.winning_bids['T_01']['winning_amr']}")
    
    assert amr1_cbba.winning_bids['T_01']['winning_amr'] == "AMR_1"
    assert amr2_cbba.winning_bids['T_01']['winning_amr'] == "AMR_1"
    assert "T_01" not in amr2_cbba.local_bundle
    print("All Step 3 Sanity Checks Passed Successfully!")
    