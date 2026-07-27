import subprocess
import time
import os

# Danh sách ánh xạ các dịch vụ trên cụm EKS (techx-tf3)
kubectl_services = [
    ("deployment/product-catalog", 3550, 8080),
    ("deployment/cart", 7070, 8080),
    ("deployment/product-reviews", 9090, 3551),
    ("deployment/recommendation", 8081, 8080),
    ("deployment/currency", 7001, 8080),
    ("deployment/shipping", 50051, 8080),
    # NOTE: PostgreSQL đã migrate sang RDS managed service.
    # Kết nối DB giờ đi qua SSM tunnel bên dưới — KHÔNG dùng kubectl port-forward tới pod cũ nữa.
]

# RDS Managed PostgreSQL — tunnel qua SSM bastion
RDS_HOST = "techx-tf3-postgres.czwcs2ocww3q.ap-southeast-1.rds.amazonaws.com"
SSM_TARGET = "i-02a8d3e39b87180ce"
RDS_LOCAL_PORT = 5433  # local port (tránh conflict với postgres local nếu có)
RDS_REMOTE_PORT = 5432
AWS_REGION = "ap-southeast-1"

print("=== STARTING EKS PORT FORWARDS IN BACKGROUND ===")
env = os.environ.copy()
env["AWS_PROFILE"] = "default"

processes = []

# Kubectl port-forwards cho các microservices
for resource_path, local_port, target_port in kubectl_services:
    cmd = ["kubectl", "port-forward", resource_path, f"{local_port}:{target_port}", "-n", "techx-tf3"]
    print(f"🚀 Spawning: {' '.join(cmd)}")
    try:
        p = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        processes.append(p)
    except Exception as e:
        print(f"❌ Failed to spawn {resource_path}: {e}")

# SSM tunnel tới RDS managed PostgreSQL
rds_ssm_cmd = [
    "aws", "ssm", "start-session",
    "--target", SSM_TARGET,
    "--document-name", "AWS-StartPortForwardingSessionToRemoteHost",
    "--parameters", f"host={RDS_HOST},portNumber={RDS_REMOTE_PORT},localPortNumber={RDS_LOCAL_PORT}",
    "--region", AWS_REGION,
]
print(f"🚀 Spawning SSM RDS tunnel: localhost:{RDS_LOCAL_PORT} → {RDS_HOST}:{RDS_REMOTE_PORT}")
try:
    p = subprocess.Popen(rds_ssm_cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    processes.append(p)
except Exception as e:
    print(f"❌ Failed to spawn SSM RDS tunnel: {e}")

print("\nWaiting 5 seconds for connections to establish...")
time.sleep(5)
print("✅ Background port forwards launched successfully!")
print(f"🗄️  RDS PostgreSQL available at localhost:{RDS_LOCAL_PORT} (via SSM tunnel)")
print("🔔 Giữ terminal này mở để duy trì kết nối. Nhấn Ctrl+C để tắt toàn bộ port-forward.")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\nTerminating all port forwards...")
    for p in processes:
        p.terminate()
    print("Cleaned up successfully.")
