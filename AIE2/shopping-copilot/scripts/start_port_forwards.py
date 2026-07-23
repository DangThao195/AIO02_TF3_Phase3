import subprocess
import time
import os

# Danh sách ánh xạ các dịch vụ trên cụm EKS (techx-tf3)
# Format: (resource_path, local_port, service_port)
kubectl_services = [
    ("svc/product-catalog", 3550, 8080),
    ("svc/cart", 7070, 8080),
    ("svc/product-reviews", 9090, 3551),
    ("svc/recommendation", 8081, 8080),
    ("svc/currency", 7001, 8080),
    ("svc/shipping", 50052, 8080),
    # NOTE: PostgreSQL đã migrate sang RDS managed service.
    # Kết nối DB giờ đi qua SSM tunnel bên dưới — KHÔNG dùng kubectl port-forward tới pod cũ nữa.
]

# EKS API Server SSM Tunnel (localhost:8443 -> EKS Cluster API 443)
EKS_HOST = "ADA05FFC84146C0AED730F78786EB320.gr7.ap-southeast-1.eks.amazonaws.com"
EKS_LOCAL_PORT = 8443
EKS_REMOTE_PORT = 443

# RDS Managed PostgreSQL — tunnel qua SSM bastion
RDS_HOST = "techx-tf3-postgres.czwcs2ocww3q.ap-southeast-1.rds.amazonaws.com"
SSM_TARGET = "i-02a8d3e39b87180ce"
RDS_LOCAL_PORT = 5433  # local port (tránh conflict với postgres local nếu có)
RDS_REMOTE_PORT = 5432
AWS_REGION = "ap-southeast-1"

print("=== STARTING EKS PORT FORWARDS IN BACKGROUND ===")
env = os.environ.copy()
if "AWS_PROFILE" not in env:
    env["AWS_PROFILE"] = "default"

processes = []

# 1. SSM tunnel tới EKS API Server (cho kubectl kết nối qua localhost:8443)
eks_ssm_cmd = [
    "aws", "ssm", "start-session",
    "--target", SSM_TARGET,
    "--document-name", "AWS-StartPortForwardingSessionToRemoteHost",
    "--parameters", f"host={EKS_HOST},portNumber={EKS_REMOTE_PORT},localPortNumber={EKS_LOCAL_PORT}",
    "--region", AWS_REGION,
]
print(f"🚀 Spawning SSM EKS API tunnel: localhost:{EKS_LOCAL_PORT} → {EKS_HOST}:{EKS_REMOTE_PORT}")
try:
    p = subprocess.Popen(eks_ssm_cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    processes.append(("SSM-EKS-API-Tunnel", p))
    # Chờ 3s để tunnel 8443 sẵn sàng trước khi kubectl kết nối
    time.sleep(3)
except Exception as e:
    print(f"❌ Failed to spawn SSM EKS API tunnel: {e}")

# 2. Kubectl port-forwards cho các microservices
for resource_path, local_port, target_port in kubectl_services:
    cmd = ["kubectl", "port-forward", resource_path, f"{local_port}:{target_port}", "-n", "techx-tf3"]
    print(f"🚀 Spawning: {' '.join(cmd)}")
    try:
        p = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        processes.append((resource_path, p))
    except Exception as e:
        print(f"❌ Failed to spawn {resource_path}: {e}")

# 3. SSM tunnel tới RDS managed PostgreSQL
rds_ssm_cmd = [
    "aws", "ssm", "start-session",
    "--target", SSM_TARGET,
    "--document-name", "AWS-StartPortForwardingSessionToRemoteHost",
    "--parameters", f"host={RDS_HOST},portNumber={RDS_REMOTE_PORT},localPortNumber={RDS_LOCAL_PORT}",
    "--region", AWS_REGION,
]
print(f"🚀 Spawning SSM RDS tunnel: localhost:{RDS_LOCAL_PORT} → {RDS_HOST}:{RDS_REMOTE_PORT}")
try:
    p = subprocess.Popen(rds_ssm_cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    processes.append(("SSM-RDS-Tunnel", p))
except Exception as e:
    print(f"❌ Failed to spawn SSM RDS tunnel: {e}")

print("\nWaiting 5 seconds for connections to establish...")
time.sleep(5)

active_count = 0
for name, p in processes:
    poll_res = p.poll()
    if poll_res is not None:
        err = p.stderr.read() if p.stderr else ""
        print(f"❌ ERROR: Process for '{name}' exited with code {poll_res}.")
        if err:
            print(f"   Detail: {err.strip()}")
    else:
        active_count += 1

if active_count == len(processes):
    print("✅ All background port forwards launched successfully!")
else:
    print(f"⚠️  WARNING: Only {active_count}/{len(processes)} port forwards are active!")
    print("👉 If kubectl failed, run: aws eks update-kubeconfig --region ap-southeast-1 --name <YOUR_CLUSTER_NAME>")

print(f"🗄️  RDS PostgreSQL available at localhost:{RDS_LOCAL_PORT} (via SSM tunnel)")
print("🔔 Giữ terminal này mở để duy trì kết nối. Nhấn Ctrl+C để tắt toàn bộ port-forward.")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\nTerminating all port forwards...")
    for name, p in processes:
        p.terminate()
    print("Cleaned up successfully.")
