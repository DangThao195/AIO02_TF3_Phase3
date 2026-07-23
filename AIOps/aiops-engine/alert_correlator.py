import logging
import json
import os
import hashlib
import time
import networkx as nx
from datetime import datetime, timezone

logger = logging.getLogger("AIOpsEngine.AlertCorrelator")

# S3 key cho topology file — dùng chung bucket với models
TOPOLOGY_S3_KEY = "topology/services.json"


class AlertCorrelator:
    def __init__(self, max_hop=2, config_path="services.json", window_seconds=600):
        self.max_hop = max_hop
        self.window_seconds = window_seconds

        # Tìm đường dẫn file config thích hợp
        if not os.path.exists(config_path):
            config_path = os.path.join("aiops-engine", config_path)

        self.config_path = config_path
        self.service_graph = {}
        self.nx_graph = nx.DiGraph()
        self.metadata = {
            "graph_version": "none",
            "graph_loaded_at": "none",
            "graph_node_count": 0,
            "graph_edge_count": 0,
            "graph_source": "local-json"
        }

        # Tải đồ thị lần đầu: ưu tiên S3 → fallback local file
        self.reload_graph()

    def _try_load_from_s3(self) -> str | None:
        """
        Thử tải services.json từ S3.
        Trả về nội dung JSON string nếu thành công, None nếu không có credential hoặc lỗi.
        """
        try:
            import boto3
            from config import S3_BUCKET_NAME

            if not os.getenv("AWS_ACCESS_KEY_ID"):
                return None

            s3 = boto3.client("s3")
            response = s3.get_object(Bucket=S3_BUCKET_NAME, Key=TOPOLOGY_S3_KEY)
            content = response["Body"].read().decode("utf-8")
            logger.info(f"Loaded services.json from s3://{S3_BUCKET_NAME}/{TOPOLOGY_S3_KEY}")
            return content
        except Exception as e:
            logger.debug(f"S3 topology load skipped: {e}")
            return None

    def reload_graph(self) -> bool:
        """
        Tải động đồ thị topology và cập nhật version/metadata.

        Thứ tự ưu tiên:
          1. S3 (topology/services.json) — luôn mới nhất dù Pod restart
          2. Local file (services.json) — fallback khi offline/no credentials
        """
        # Thử S3 trước
        s3_content = self._try_load_from_s3()
        if s3_content:
            try:
                data = json.loads(s3_content)
                self._apply_graph_data(data, s3_content, source="s3")
                # Sync về local disk để fallback hoạt động khi mất kết nối S3
                try:
                    with open(self.config_path, "w", encoding="utf-8") as f:
                        f.write(s3_content)
                except Exception:
                    pass
                return True
            except Exception as e:
                logger.error(f"Failed to parse S3 topology content: {e}. Falling back to local.")

        # Fallback: local file
        if not os.path.exists(self.config_path):
            logger.error(f"Service graph file not found at {self.config_path}. Using empty graph.")
            self.service_graph = {}
            return False

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                content = f.read()
            data = json.loads(content)
            self._apply_graph_data(data, content, source="local-json")
            return True
        except Exception as e:
            logger.error(f"Failed to load service graph: {e}")
            return False

    def _apply_graph_data(self, data: dict, raw_content: str, source: str):
        """Áp dụng dữ liệu topology vào graph, tính metadata và build NetworkX DiGraph."""
        hasher = hashlib.md5()
        hasher.update(raw_content.encode("utf-8"))
        graph_version = f"g-{hasher.hexdigest()[:10]}"

        self.service_graph = data

        nodes: set[str] = set()
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
            "graph_source": source
        }

        # Rebuild NetworkX DiGraph: edge u → v = "u gọi v" (u phụ thuộc v)
        self.nx_graph = nx.DiGraph()
        for u, neighbors in data.items():
            for v in neighbors:
                self.nx_graph.add_edge(u, v)

        logger.info(
            f"Service graph loaded [{source}] version={graph_version} "
            f"({len(nodes)} nodes, {edges} edges)"
        )

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
        """[LEGACY] Lựa chọn culprit tiềm năng nằm ở hạ nguồn sâu nhất (cách xa frontend nhất).
        Kept for backward compatibility with correlate_alerts(). Prefer select_rca_candidate_scored()."""
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

    def _build_reverse_adj(self) -> dict:
        """[LEGACY] Kept for internal reference. Prefer nx_graph for traversal."""
        rev = {}
        for u, neighbors in self.service_graph.items():
            for v in neighbors:
                if v not in rev:
                    rev[v] = set()
                rev[v].add(u)
            if u not in rev:
                rev[u] = set()
        return rev

    def _upstream_distance(self, service: str, candidate: str) -> int:
        """[LEGACY] Kept for backward compat. Prefer nx.ancestors() via select_rca_candidate_scored().
        Trả về số hop ngược dòng từ service đến candidate, 999 nếu không liên thông."""
        if service == candidate:
            return 0
        rev = self._build_reverse_adj()
        queue = [(service, 0)]
        visited = {service}
        while queue:
            node, dist = queue.pop(0)
            for parent in rev.get(node, []):
                if parent == candidate:
                    return dist + 1
                if parent not in visited:
                    visited.add(parent)
                    queue.append((parent, dist + 1))
        return 999

    def select_rca_candidate_scored(
        self,
        services_with_time: list[tuple[str, float]]
    ) -> str:
        """
        [BUG 2 FIX — NetworkX] Chọn culprit dựa trên 3 tín hiệu theo ADR-007:
          1. Upstream score: đếm số victim service nào mà candidate là ancestor
             (theo NetworkX DiGraph — edge A→B nghĩa là A gọi B, tức B là downstream của A).
             candidate là upstream của victim ⟺ candidate ∈ nx.ancestors(G_reversed, victim)
             ⟺ victim ∈ nx.descendants(G, candidate)
          2. First-drift time: fired_at sớm nhất là culprit khi upstream_score bằng nhau.
          3. Tie-break cuối: thứ tự alphabet.

        Args:
            services_with_time: list of (service_name, fired_at_timestamp)
        Returns:
            culprit service name
        """
        if not services_with_time:
            return "unknown-service"
        if len(services_with_time) == 1:
            return services_with_time[0][0]

        services = [s for s, _ in services_with_time]
        fired_at = {s: t for s, t in services_with_time}
        services_set = set(services)

        best_service = services[0]
        best_upstream = -1
        best_drift = float("inf")

        for candidate in services:
            # Ngữ nghĩa graph: u -> v nghĩa là u gọi v (u phụ thuộc v).
            # nx.ancestors(G, candidate) trả về tất cả node có đường đến candidate
            # tức là tất cả service phụ thuộc (gọi) candidate → candidate là upstream của chúng.
            # Candidate nào có nhiều callers/dependents bị lỗi cùng lúc nhất là Root Cause.
            if candidate in self.nx_graph:
                dependents = nx.ancestors(self.nx_graph, candidate)
            else:
                dependents = set()
            upstream_score = len(dependents & services_set)

            first_drift = fired_at.get(candidate, float("inf"))

            # Ưu tiên: (1) upstream_score cao hơn thắng,
            #          (2) nếu bằng nhau → fired_at sớm hơn thắng,
            #          (3) tie-break cuối: tên alphabet nhỏ hơn thắng
            if (upstream_score > best_upstream
                    or (upstream_score == best_upstream and first_drift < best_drift)
                    or (upstream_score == best_upstream and first_drift == best_drift
                        and candidate < best_service)):
                best_upstream = upstream_score
                best_drift = first_drift
                best_service = candidate

        logger.info(
            f"[NetworkX RCA] candidates={[(s, fired_at[s]) for s, _ in services_with_time]} "
            f"→ culprit={best_service} "
            f"(upstream_score={best_upstream}, first_drift={best_drift:.3f})"
        )
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

    def correlate_alerts_windowed(self, alerts: list[dict]) -> list[dict]:
        """
        [BUG 1 + BUG 2 FIX] Correlate alerts với time-window clustering và upstream RCA scoring.

        Quy trình:
          1. Đọc fired_at từ mỗi alert (key "fired_at", mặc định = now).
          2. Gom các alert có chênh lệch thời gian <= window_seconds VÀ cùng
             topology cluster (khoảng cách <= max_hop) vào cùng 1 cluster.
          3. Chọn culprit bằng select_rca_candidate_scored() (upstream + first-drift).

        Args:
            alerts: list of alert dicts, mỗi dict có thể chứa key "fired_at" (float timestamp).
        Returns:
            list of cluster dicts (giống format correlate_alerts() nhưng culprit đúng hơn).
        """
        if not alerts:
            return []

        now = time.time()

        # --- Bước 1: Normalize và đọc fired_at ---
        normalized = []
        for a in alerts:
            labels = a.get("labels", {})
            annotations = a.get("annotations", {})
            service   = labels.get("service", a.get("service", "unknown"))
            alertname = labels.get("alertname", a.get("alertname", "UnknownAlert"))
            severity  = labels.get("severity", a.get("severity", "warning"))
            trace_id  = annotations.get("trace_id", labels.get("trace_id", a.get("trace_id", "mock-trace-id")))
            fired_at  = float(a.get("fired_at", now))
            normalized.append({
                "service": service,
                "alertname": alertname,
                "severity": severity,
                "trace_id": trace_id,
                "fired_at": fired_at,
            })

        # --- Bước 2: Dedup bằng fingerprint ---
        seen_fps: dict[str, dict] = {}
        for item in normalized:
            fp = f"{item['service']}|{item['alertname']}|{item['severity']}"
            if fp not in seen_fps:
                seen_fps[fp] = {**item, "fingerprint": fp, "count": 1, "raw_alerts": [item]}
            else:
                seen_fps[fp]["count"] += 1
                # Giữ fired_at SỚM nhất (first-drift)
                if item["fired_at"] < seen_fps[fp]["fired_at"]:
                    seen_fps[fp]["fired_at"] = item["fired_at"]
                seen_fps[fp]["raw_alerts"].append(item)

        items = list(seen_fps.values())

        # --- Bước 3: Union-Find gộp bởi (time_window AND topology) ---
        parent = {item["fingerprint"]: item["fingerprint"] for item in items}

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x: str, y: str) -> None:
            root_x, root_y = find(x), find(y)
            if root_x != root_y:
                parent[root_x] = root_y

        for i, item1 in enumerate(items):
            for item2 in items[i + 1:]:
                time_close = abs(item1["fired_at"] - item2["fired_at"]) <= self.window_seconds
                topo_close = self.get_distance(item1["service"], item2["service"]) <= self.max_hop
                if time_close and topo_close:
                    union(item1["fingerprint"], item2["fingerprint"])

        # --- Bước 4: Gom nhóm ---
        groups: dict[str, list] = {}
        for item in items:
            root = find(item["fingerprint"])
            groups.setdefault(root, []).append(item)

        # --- Bước 5: Chọn culprit bằng upstream scoring ---
        clusters = []
        for idx, (root, group_items) in enumerate(groups.items()):
            services_with_time = [(g["service"], g["fired_at"]) for g in group_items]
            culprit = self.select_rca_candidate_scored(services_with_time)
            services = sorted({g["service"] for g in group_items})
            total_count = sum(g["count"] for g in group_items)
            trace_id = min(group_items, key=lambda g: g["fired_at"])["trace_id"]

            clusters.append({
                "cluster_id": f"cluster-{idx:03d}",
                "alert_count": total_count,
                "services": services,
                "alert_names": sorted({g["alertname"] for g in group_items}),
                "culprit_service": culprit,
                "trace_id": trace_id,
                "items": group_items,
            })

        logger.info(
            f"[Windowed] Clustered {len(alerts)} alerts into {len(clusters)} clusters "
            f"(window={self.window_seconds}s, max_hop={self.max_hop})."
        )
        return clusters
