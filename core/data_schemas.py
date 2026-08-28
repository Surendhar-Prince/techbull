"""
Data Schemas and Network Payload Contracts for SIH26123.
Defines strictly typed dataclasses with built-in JSON/UDP serialization.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
import json
import hashlib
import time


@dataclass
class Task:
    task_id: str
    pickup_node: str
    dropoff_node: str
    urgency: float = 1.0          # Multiplier for CBBA bidding
    payload_weight_kg: float = 5.0
    status: str = "UNASSIGNED"     # UNASSIGNED, CLAIMED, IN_PROGRESS, COMPLETED
    assigned_amr: Optional[str] = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        return cls(**data)


@dataclass
class StateIntentPacket:
    """
    Broadcasted at 10 Hz over UDP by each AMR Parasite Node.
    """
    amr_id: str
    timestamp: float
    current_node: str
    target_node: str
    planned_path: List[str]            # Full node path: ["N_01", "N_04", "N_07"]
    claimed_mutex: List[str]           # Next 2-3 lookahead nodes: ["N_01", "N_04"]
    battery: float                     # Percentage 0.0 - 100.0
    payload_status: str                # "EMPTY" or "LOADED"
    wait_time_sec: float               # Time spent yielding (for starvation prevention)
    fsm_state: str                     # "IDLE", "BIDDING", "PLANNING", "NAVIGATING", "YIELDING", "REVERSING"
    
    # --- All variables with default values MUST go at the bottom ---
    active_task_id: Optional[str] = None
    task_pool_hash: str = ""           # MD5 hash of local active task IDs for Gossip Protocol
    task_bundle: Dict[str, float] = field(default_factory=dict)  # <--- CORRECTLY PLACED HERE
    packet_type: str = "STATE_INTENT"

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    def to_bytes(self) -> bytes:
        return self.to_json().encode("utf-8")

    @classmethod
    def from_json(cls, json_str: str) -> "StateIntentPacket":
        data = json.loads(json_str)
        return cls(**data)

    @classmethod
    def from_bytes(cls, raw_bytes: bytes) -> "StateIntentPacket":
        return cls.from_json(raw_bytes.decode("utf-8"))


@dataclass
class GossipSyncPacket:
    """
    Triggered when an AMR detects that a peer has an outdated task_pool_hash.
    """
    sender_id: str
    missing_tasks: List[Task]
    timestamp: float = field(default_factory=time.time)
    packet_type: str = "GOSSIP_SYNC"

    def to_json(self) -> str:
        d = asdict(self)
        d["missing_tasks"] = [t.to_dict() if isinstance(t, Task) else t for t in self.missing_tasks]
        return json.dumps(d)

    def to_bytes(self) -> bytes:
        return self.to_json().encode("utf-8")

    @classmethod
    def from_json(cls, json_str: str) -> "GossipSyncPacket":
        data = json.loads(json_str)
        tasks = [Task.from_dict(t) for t in data.get("missing_tasks", [])]
        return cls(
            sender_id=data["sender_id"],
            missing_tasks=tasks,
            timestamp=data.get("timestamp", time.time()),
            packet_type=data.get("packet_type", "GOSSIP_SYNC")
        )

    @classmethod
    def from_bytes(cls, raw_bytes: bytes) -> "GossipSyncPacket":
        return cls.from_json(raw_bytes.decode("utf-8"))


@dataclass
class GenesisTaskPacket:
    """
    Injected once via Laptop 1 (or any terminal) to seed new warehouse orders.
    """
    tasks: List[Task]
    sender_id: str = "LAP_MAP"
    timestamp: float = field(default_factory=time.time)
    packet_type: str = "GENESIS_TASK"

    def to_json(self) -> str:
        d = asdict(self)
        d["tasks"] = [t.to_dict() if isinstance(t, Task) else t for t in self.tasks]
        return json.dumps(d)

    def to_bytes(self) -> bytes:
        return self.to_json().encode("utf-8")

    @classmethod
    def from_json(cls, json_str: str) -> "GenesisTaskPacket":
        data = json.loads(json_str)
        tasks = [Task.from_dict(t) for t in data.get("tasks", [])]
        return cls(
            tasks=tasks,
            sender_id=data.get("sender_id", "LAP_MAP"),
            timestamp=data.get("timestamp", time.time()),
            packet_type=data.get("packet_type", "GENESIS_TASK")
        )

    @classmethod
    def from_bytes(cls, raw_bytes: bytes) -> "GenesisTaskPacket":
        return cls.from_json(raw_bytes.decode("utf-8"))


# ==========================================
# Utility Functions for Hash Calculation
# ==========================================
def calculate_task_pool_hash(task_dict: Dict[str, Any]) -> str:
    """
    Generates a deterministic MD5 hash of all active/uncompleted task IDs in memory.
    """
    if not task_dict:
        return "EMPTY_POOL"
    
    active_ids = []
    for t_id, record in task_dict.items():
        # Handle both direct Task objects and nested dictionary records
        if isinstance(record, dict):
            task_obj = record.get("task_obj")
            if task_obj and getattr(task_obj, "status", "UNASSIGNED") != "COMPLETED":
                active_ids.append(t_id)
        else:
            if getattr(record, "status", "UNASSIGNED") != "COMPLETED":
                active_ids.append(t_id)
                
    if not active_ids:
        return "EMPTY_POOL"
        
    hash_payload = ",".join(sorted(active_ids))
    return hashlib.md5(hash_payload.encode("utf-8")).hexdigest()[:8]


# ==========================================
# Quick Sanity Test
# ==========================================
if __name__ == "__main__":
    # Test 1: Task Creation and Hash
    t1 = Task(task_id="T_101", pickup_node="N_07", dropoff_node="N_13", urgency=1.2)
    t2 = Task(task_id="T_102", pickup_node="N_09", dropoff_node="N_15")
    task_pool = {t1.task_id: t1, t2.task_id: t2}
    pool_hash = calculate_task_pool_hash(task_pool)
    print(f"[TEST 1] Calculated Pool Hash: {pool_hash}")

    # Test 2: StateIntentPacket Serialization / Deserialization
    pkt = StateIntentPacket(
        amr_id="AMR_1",
        timestamp=time.time(),
        current_node="N_01",
        target_node="N_07",
        planned_path=["N_01", "N_04", "N_07"],
        claimed_mutex=["N_01", "N_04"],
        battery=94.5,
        payload_status="EMPTY",
        wait_time_sec=0.0,
        fsm_state="NAVIGATING",
        active_task_id="T_101",
        task_pool_hash=pool_hash
    )
    raw = pkt.to_bytes()
    decoded = StateIntentPacket.from_bytes(raw)
    assert decoded.amr_id == "AMR_1"
    assert decoded.claimed_mutex == ["N_01", "N_04"]
    print(f"[TEST 2] StateIntentPacket Verified ({len(raw)} bytes transferred).")

    # Test 3: Genesis Task Packet Serialization
    gen_pkt = GenesisTaskPacket(tasks=[t1, t2])
    gen_raw = gen_pkt.to_bytes()
    gen_decoded = GenesisTaskPacket.from_bytes(gen_raw)
    assert len(gen_decoded.tasks) == 2
    assert gen_decoded.tasks[0].task_id == "T_101"
    print(f"[TEST 3] GenesisTaskPacket Verified ({len(gen_raw)} bytes transferred).")
    print("All Step 1 Schema Sanity Checks Passed Successfully!")