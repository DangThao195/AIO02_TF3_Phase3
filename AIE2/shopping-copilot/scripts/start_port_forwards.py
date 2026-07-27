import subprocess
import time
import os
import json

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

# RDS Managed PostgreSQL — tunnel qua SSM bastion
RDS_HOST = "techx-tf3-postgres.czwcs2ocww3q.ap-southeast-1.rds.amazonaws.com"
RDS_LOCAL_PORT = 5433  # local port (tránh conflict với postgres local nếu có)
RDS_REMOTE_PORT = 5432
AWS_REGION = "ap-southeast-1"
CLUSTER_NAME = "techx-corp-tf3"

# Auto-discover EKS endpoint và Bastion ID
print("[AUTO-DISCOVERING EKS ENDPOINT & BASTION ID]")
try:
    # Get EKS endpoint
    eks_result = subprocess.run(
        ["aws", "eks", "describe-cluster", "--name", CLUSTER_NAME, "--region", AWS_REGION,
         "--query", "cluster.endpoint", "--output", "text"],
        capture_output=True, text=True, check=True
    )
    EKS_HOST = eks_result.stdout.strip().replace("https://", "").replace("http://", "")
    print(f"[OK] EKS Host: {EKS_HOST}")
except Exception as e:
    print(f"[ERROR] Failed to get EKS endpoint: {e}")
    EKS_HOST = None

# Get Bastion ID
try:
    bastion_result = subprocess.run(
        ["aws", "ec2", "describe-instances", "--region", AWS_REGION,
         "--filters", "Name=tag:Name,Values=techx-corp-tf3-bastion", "Name=instance-state-name,Values=running",
         "--query", "Reservations[].Instances[].InstanceId", "--output", "text"],
        capture_output=True, text=True, check=True
    )
    SSM_TARGET = bastion_result.stdout.strip()
    if SSM_TARGET:
        print(f"[OK] Bastion ID: {SSM_TARGET}")
    else:
        print("[WARN] No running bastion found. Using fallback...")
        SSM_TARGET = "i-02a8d3e39b87180ce"
except Exception as e:
    print(f"[ERROR] Failed to get Bastion ID: {e}")
    SSM_TARGET = "i-02a8d3e39b87180ce"

EKS_LOCAL_PORT = 8443
EKS_REMOTE_PORT = 443

print("\n[STARTING EKS PORT FORWARDS]")
env = os.environ.copy()
if "AWS_PROFILE" not in env:
    env["AWS_PROFILE"] = "default"

processes = []

# Safety check
if not EKS_HOST or not SSM_TARGET:
    print("[FATAL] Could not discover EKS_HOST or SSM_TARGET")
    exit(1)

print(f"Using: EKS_HOST={EKS_HOST}, BASTION_ID={SSM_TARGET}\n")

# 1. SSM tunnel to EKS API Server
eks_ssm_cmd = [
    "aws", "ssm", "start-session",
    "--target", SSM_TARGET,
    "--document-name", "AWS-StartPortForwardingSessionToRemoteHost",
    "--parameters", f"host={EKS_HOST},portNumber={EKS_REMOTE_PORT},localPortNumber={EKS_LOCAL_PORT}",
    "--region", AWS_REGION,
]
print(f"[INFO] Spawning SSM EKS API tunnel: localhost:{EKS_LOCAL_PORT} -> {EKS_HOST}:{EKS_REMOTE_PORT}")
try:
    p = subprocess.Popen(eks_ssm_cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    processes.append(("SSM-EKS-API-Tunnel", p))
    time.sleep(3)
except Exception as e:
    print(f"[ERROR] Failed to spawn SSM EKS API tunnel: {e}")

# 2. Kubectl port-forwards for microservices
for resource_path, local_port, target_port in kubectl_services:
    cmd = ["kubectl", "port-forward", resource_path, f"{local_port}:{target_port}", "-n", "techx-tf3"]
    print(f"[INFO] Spawning: {' '.join(cmd)}")
    try:
        p = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        processes.append((resource_path, p))
    except Exception as e:
        print(f"[ERROR] Failed to spawn {resource_path}: {e}")

# 3. SSM tunnel to RDS managed PostgreSQL
rds_ssm_cmd = [
    "aws", "ssm", "start-session",
    "--target", SSM_TARGET,
    "--document-name", "AWS-StartPortForwardingSessionToRemoteHost",
    "--parameters", f"host={RDS_HOST},portNumber={RDS_REMOTE_PORT},localPortNumber={RDS_LOCAL_PORT}",
    "--region", AWS_REGION,
]
print(f"[INFO] Spawning SSM RDS tunnel: localhost:{RDS_LOCAL_PORT} -> {RDS_HOST}:{RDS_REMOTE_PORT}")
try:
    p = subprocess.Popen(rds_ssm_cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    processes.append(("SSM-RDS-Tunnel", p))
except Exception as e:
    print(f"[ERROR] Failed to spawn SSM RDS tunnel: {e}")

print("\n[WAITING FOR PORT CONNECTIONS]")

import socket

def test_port_ready(port, name, max_retries=15, delay=1):
    """Test if a port is accepting connections"""
    for attempt in range(max_retries):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('127.0.0.1', port))
            sock.close()
            if result == 0:
                print(f"[OK] {name} ready on port {port}")
                return True
        except:
            pass
        time.sleep(delay)
    print(f"[FAIL] {name} NOT ready on port {port}")
    return False

# Test critical ports
ports_ok = True
for port, name in [(EKS_LOCAL_PORT, "EKS"), (RDS_LOCAL_PORT, "RDS")]:
    if not test_port_ready(port, name):
        ports_ok = False

# Check process status
active = sum(1 for _, p in processes if p.poll() is None)
print(f"\n[INFO] {active}/{len(processes)} port-forward processes active")

if ports_ok and active == len(processes):
    print("[SUCCESS] All port-forwards ready!")
else:
    print("[WARN] Some connections may not be ready")

try:
    print("\n[LISTENING] Press Ctrl+C to stop all port-forwards...")
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\n[STOPPING] Terminating all port forwards...")
    for name, p in processes:
        p.terminate()
    print("[DONE] Cleaned up successfully.")
