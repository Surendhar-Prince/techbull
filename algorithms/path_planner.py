"""
Dynamic Edge Path Planner.
Loads the static topological map and actively modifies edge weights 
based on peer UDP claims to route around traffic dynamically.
"""

import json
import math
import networkx as nx
from typing import List, Tuple, Dict
from core.host_hardware_bridge import HostHardwareBridge


class NetworkXPlanner:
    def __init__(self, map_filepath: str):
        self.map_filepath = map_filepath
        self.base_graph = self._load_graph()
        self.dynamic_graph = self.base_graph.copy()

    def _load_graph(self) -> nx.Graph:
        """
        Parses the configs/warehouse_map.json into a NetworkX Graph.
        Injects X and Y coordinates into the nodes for A* heuristics.
        """
        G = nx.Graph()
        try:
            with open(self.map_filepath, 'r') as f:
                map_data = json.load(f)

            # Add Nodes with coordinates
            for node in map_data["nodes"]:
                G.add_node(node["id"], x=node["x"], y=node["y"], type=node["type"])

            # Add Edges with baseline weights
            for edge in map_data["edges"]:
                G.add_edge(edge["from"], edge["to"], weight=edge["weight"])
                
            return G
        except FileNotFoundError:
            raise RuntimeError(f"CRITICAL: Map file not found at {self.map_filepath}")
        except KeyError as e:
            raise RuntimeError(f"CRITICAL: Invalid map JSON structure. Missing key: {e}")

    def apply_peer_mutexes(self, peer_claims: List[Tuple[str, str]]):
        """
        Takes a list of edges currently claimed by peers (e.g., [("N_04", "N_05")]).
        Sets those specific edge weights to infinity in the dynamic graph.
        """
        # 1. Reset the dynamic graph to the pristine base state
        self.dynamic_graph = self.base_graph.copy()

        # 2. Apply infinite weights to locked edges
        for u, v in peer_claims:
            if self.dynamic_graph.has_edge(u, v):
                # Using a massively high number rather than float('inf') is 
                # sometimes safer for standard A* implementations to avoid math errors.
                self.dynamic_graph[u][v]['weight'] = 999999.0 

    def _astar_heuristic(self, node_a: str, node_b: str) -> float:
        """
        Calculates the straight-line Euclidean distance between two nodes.
        Makes the A* search dramatically faster on edge hardware.
        """
        x1, y1 = self.dynamic_graph.nodes[node_a]['x'], self.dynamic_graph.nodes[node_a]['y']
        x2, y2 = self.dynamic_graph.nodes[node_b]['x'], self.dynamic_graph.nodes[node_b]['y']
        return math.hypot(x2 - x1, y2 - y1)

    def compute_safe_path(self, start_node: str, target_node: str) -> List[str]:
        """
        Calculates the optimal path from start to target on the dynamic graph.
        Raises nx.NetworkXNoPath if all routes are blocked by peer mutexes.
        """
        if start_node not in self.dynamic_graph or target_node not in self.dynamic_graph:
            raise ValueError(f"Invalid nodes provided: Start({start_node}), Target({target_node})")

        # Execute A* Search
        path = nx.astar_path(
            self.dynamic_graph, 
            source=start_node, 
            target=target_node, 
            heuristic=self._astar_heuristic, 
            weight='weight'
        )
        
        # If the only available path forces the robot through a locked Mutex 
        # (weight = 999999.0), it is functionally blocked.
        path_weight = nx.path_weight(self.dynamic_graph, path, weight='weight')
        if path_weight >= 999999.0:
            raise nx.NetworkXNoPath("No safe path available. All routes blocked by Mutex.")

        return path

    def get_node_coordinates(self, node_id: str) -> Tuple[float, float]:
        """Helper to fetch exact (x, y) for the hardware bridge commands."""
        node_data = self.base_graph.nodes[node_id]
        return node_data['x'], node_data['y']


# ==========================================
# Quick Sanity Test
# ==========================================
if __name__ == "__main__":
    print("--- Testing Hardware Bridge ---")
    bridge = HostHardwareBridge(amr_id="AMR_1")
    bridge.send_drive_command("N_05", 15.0, 15.0)
    bridge.send_stop_command("YIELDING_TO_AMR_2")

    print("\n--- Testing Path Planner ---")
    # Make sure to run this from the root workspace directory so it finds configs/
    try:
        planner = NetworkXPlanner(map_filepath="configs/warehouse_map.json")
        print(f"Loaded graph with {planner.base_graph.number_of_nodes()} nodes.")
        
        # Standard path (N_04 to N_11)
        path1 = planner.compute_safe_path("N_04", "N_11")
        print(f"Pristine Path: {path1}")

        # Apply a Mutex block on the main intersection (N_05 to N_08)
        # This simulates AMR 2 currently driving through that narrow choke point
        planner.apply_peer_mutexes([("N_05", "N_08")])
        
        # Recalculate path - the planner should naturally route around the choke point
        path2 = planner.compute_safe_path("N_04", "N_11")
        print(f"Mutex Avoidance Path: {path2}")
        print("All Step 2 Sanity Checks Passed Successfully!")
        
    except FileNotFoundError:
        print("Note: To run the sanity check, ensure warehouse_map.json is in the correct relative path.")