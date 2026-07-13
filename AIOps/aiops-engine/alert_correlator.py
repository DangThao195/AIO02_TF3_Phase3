import logging
import json
import os
import hashlib
from datetime import datetime, timezone

logger = logging.getLogger("AIOpsEngine.AlertCorrelator")

class AlertCorrelator:
    def __init__(self, max_hop=2, config_path="services.json"):
        self.max_hop = max_hop
        
        # Tìm đường dẫn file config thích hợp
        if not os.path.exists(config_path):
            config_path = os.path.join("aiops-engine", config_path)
            
        self.config_path = config_path
        self.service_graph = {}
        self.metadata = {
            "graph_version": "none",
            "graph_loaded_at": "none",
            "graph_node_count": 0,
            "graph_edge_count": 0,
            "graph_source": "local-json"
        }
        
        # Tải đồ thị lần đầu
        self.reload_graph()

    def reload_graph(self) -> bool:
        """Tải động đồ thị từ services.json và cập nhật version/metadata."""
        if not os.path.exists(self.config_path):
            logger.error(f"Service graph file not found at {self.config_path}. Using fallback empty graph.")
            self.service_graph = {}
            return False
            
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                content = f.read()
                data = json.loads(content)
                
            # Tính mã hash md5 đại diện cho phiên bản của đồ thị (Graph Versioning)
            hasher = hashlib.md5()
            hasher.update(content.encode("utf-8"))
            graph_version = f"g-{hasher.hexdigest()[:10]}"
            
            self.service_graph = data
            
            # Tính toán thống kê đồ thị
            nodes = set()
            edges = 0
            for u, neighbors in data.items():
                nodes.add(u)
                for v in neighbors:
                    nodes.add(v)
                    edges += 1
                    
            self.metadata = {
                "graph_version": graph_version,
                "graph_loaded_at": datetime.now(timezone.utc).isoformat(),
                "graph_node_count": len(nodes),
                "graph_edge_count": edges,
                "graph_source": "manual-json"
            }
            logger.info(f"Successfully loaded service graph version {graph_version} ({len(nodes)} nodes, {edges} edges)")
            return True
        except Exception as e:
            logger.error(f"Failed to load service graph: {e}")
            return False

    def get_distance(self, s1: str, s2: str) -> int:
        """Tính khoảng cách ngắn nhất vô hướng giữa 2 microservices dựa trên đồ thị hiện tại."""
        if s1 == s2:
            return 0
            
        # Xây dựng danh sách kề vô hướng từ đồ thị có hướng nạp động
        adj = {}
        for u, neighbors in self.service_graph.items():
            if u not in adj:
                adj[u] = set()
            for v in neighbors:
                adj[u].add(v)
                if v not in adj:
                    adj[v] = set()
                adj[v].add(u)
        
        if s1 not in adj or s2 not in adj:
            return 999  # Không kết nối
            
        # BFS
        queue = [(s1, 0)]
        visited = {s1}
        for u, dist in queue:
            if u == s2:
                return dist
            for neighbor in adj.get(u, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, dist + 1))
        return 999

    def fingerprint(self, alert: dict) -> str:
        """Tạo fingerprint định danh alert trùng lặp để dedup."""
        service = alert.get("labels", {}).get("service", alert.get("service", "unknown"))
        alertname = alert.get("labels", {}).get("alertname", alert.get("alertname", "UnknownAlert"))
        severity = alert.get("labels", {}).get("severity", alert.get("severity", "warning"))
        return f"{service}|{alertname}|{severity}"

    def select_rca_candidate(self, services: list[str]) -> str:
        """Lựa chọn culprit tiềm năng nằm ở hạ nguồn sâu nhất (cách xa frontend nhất)."""
        if not services:
            return "unknown-service"
        if len(services) == 1:
            return services[0]
            
        best_service = services[0]
        max_dist = -1
        for s in services:
            dist = self.get_distance("frontend", s)
            if dist != 999 and dist > max_dist:
                max_dist = dist
                best_service = s
        return best_service

    def correlate_alerts(self, alerts: list[dict]) -> list[dict]:
        """
        Gộp nhóm (Clustering) danh sách alerts đầu vào dựa trên:
        - Layer 1: Fingerprint Deduplication
        - Layer 3: Topology Correlation
        """
        if not alerts:
            return []

        # Layer 1: Dedup trùng lặp
        dedupped = {}
        for a in alerts:
            labels = a.get("labels", {})
            annotations = a.get("annotations", {})
            
            service = labels.get("service", a.get("service", "unknown"))
            alertname = labels.get("alertname", a.get("alertname", "UnknownAlert"))
            severity = labels.get("severity", a.get("severity", "warning"))
            trace_id = annotations.get("trace_id", labels.get("trace_id", a.get("trace_id", "mock-trace-id")))
            
            normalized_alert = {
                "service": service,
                "alertname": alertname,
                "severity": severity,
                "trace_id": trace_id
            }
            
            fp = self.fingerprint(normalized_alert)
            if fp not in dedupped:
                dedupped[fp] = {
                    "fingerprint": fp,
                    "service": service,
                    "alertname": alertname,
                    "severity": severity,
                    "trace_id": trace_id,
                    "count": 1,
                    "raw_alerts": [normalized_alert]
                }
            else:
                dedupped[fp]["count"] += 1
                dedupped[fp]["raw_alerts"].append(normalized_alert)

        items = list(dedupped.values())

        # Layer 3: Topology correlation (Union-Find)
        parent = {item["fingerprint"]: item["fingerprint"] for item in items}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x, y):
            root_x = find(x)
            root_y = find(y)
            if root_x != root_y:
                parent[root_x] = root_y

        for i, item1 in enumerate(items):
            for item2 in items[i+1:]:
                s1 = item1["service"]
                s2 = item2["service"]
                dist = self.get_distance(s1, s2)
                if dist <= self.max_hop:
                    union(item1["fingerprint"], item2["fingerprint"])

        groups = {}
        for item in items:
            root = find(item["fingerprint"])
            if root not in groups:
                groups[root] = []
            groups[root].append(item)

        clusters = []
        for idx, (root, group_items) in enumerate(groups.items()):
            services = sorted(list({item["service"] for item in group_items}))
            total_count = sum(item["count"] for item in group_items)
            alert_names = sorted(list({item["alertname"] for item in group_items}))
            trace_id = group_items[0]["trace_id"]
            
            culprit = self.select_rca_candidate(services)
            
            clusters.append({
                "cluster_id": f"cluster-{idx:03d}",
                "alert_count": total_count,
                "services": services,
                "alert_names": alert_names,
                "culprit_service": culprit,
                "trace_id": trace_id,
                "items": group_items
            })

        logger.info(f"Alert correlation complete. Clustered {len(alerts)} alerts into {len(clusters)} unique incident clusters.")
        return clusters
