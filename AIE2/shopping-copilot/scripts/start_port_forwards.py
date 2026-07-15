import subprocess
import time
import os

# Danh sách ánh xạ các dịch vụ trên cụm EKS (techx-tf3)
services = [
    ("deployment/product-catalog", 3550, 8080),
    ("deployment/cart", 7070, 8080),
    ("deployment/product-reviews", 9090, 3551),
    ("deployment/recommendation", 8081, 8080),
    ("deployment/currency", 7001, 8080),
    ("deployment/shipping", 50051, 8080),
    ("svc/postgresql", 5432, 5432)  # Port-forward PostgreSQL
]

print("=== STARTING EKS PORT FORWARDS IN BACKGROUND ===")
env = os.environ.copy()
env["AWS_PROFILE"] = "techx-corp"

processes = []
for resource_path, local_port, target_port in services:
    cmd = ["kubectl", "port-forward", resource_path, f"{local_port}:{target_port}", "-n", "techx-tf3"]
    print(f"🚀 Spawning: {' '.join(cmd)}")
    try:
        p = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        processes.append(p)
    except Exception as e:
        print(f"❌ Failed to spawn {resource_path}: {e}")

print("\nWaiting 5 seconds for connections to establish...")
time.sleep(5)
print("✅ Background port forwards launched successfully!")
print("🔔 Giữ terminal này mở để duy trì kết nối. Nhấn Ctrl+C để tắt toàn bộ port-forward.")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\nTerminating all port forwards...")
    for p in processes:
        p.terminate()
    print("Cleaned up successfully.")
