"""
restart_tunnels.py - Khởi động lại SSM EKS/RDS Tunnel và tất cả kubectl port-forwards.
Có Auto-Healing Watchdog: Tự động khởi động lại (auto-restart) khi SSM Session hoặc port-forward bị ngắt/chết!
"""
import os
import subprocess
import time
import socket
import boto3
from dotenv import load_dotenv

load_dotenv()

REGION       = os.getenv("AWS_REGION", "ap-southeast-1")
CLUSTER_NAME = os.getenv("EKS_CLUSTER_NAME", "techx-corp-tf3")
ACCOUNT_ID   = os.getenv("AWS_ACCOUNT_ID", "197826770971")
BASTION_TAG  = os.getenv("BASTION_TAG_NAME", "techx-corp-tf3-bastion")
NAMESPACE    = os.getenv("EKS_NAMESPACE", "techx-tf3")
RDS_HOST     = os.getenv("RDS_HOST", "techx-tf3-postgres.czwcs2ocww3q.ap-southeast-1.rds.amazonaws.com")
RDS_PORT     = int(os.getenv("RDS_REMOTE_PORT", "5432"))
RDS_LOCAL    = int(os.getenv("RDS_LOCAL_PORT", "5433"))
PROFILE      = os.getenv("AWS_PROFILE", "default")

SERVICES = [
    ("deployment/product-catalog", 3550, 8080),
    ("deployment/cart",            7070, 8080),
    ("deployment/product-reviews", 9090, 3551),
    ("deployment/recommendation",  8081, 8080),
    ("deployment/currency",        7001, 8080),
    ("deployment/shipping",        50051, 8080),
    ("deployment/shipping",        50052, 8080),
]


def get_bastion_and_endpoint():
    session = boto3.Session(profile_name=PROFILE)
    ec2 = session.client("ec2", region_name=REGION)
    r = ec2.describe_instances(Filters=[
        {"Name": "tag:Name",               "Values": [BASTION_TAG]},
        {"Name": "instance-state-name",    "Values": ["running"]},
    ])
    bastion_id = r["Reservations"][0]["Instances"][0]["InstanceId"]

    eks = session.client("eks", region_name=REGION)
    endpoint = eks.describe_cluster(name=CLUSTER_NAME)["cluster"]["endpoint"].replace("https://", "")
    return bastion_id, endpoint


def check_port(port: int, host: str = "127.0.0.1") -> bool:
    s = socket.socket()
    s.settimeout(2)
    ok = s.connect_ex((host, port)) == 0
    s.close()
    return ok


def launch_ssm_eks(bastion_id, eks_endpoint, env):
    return subprocess.Popen([
        "aws", "ssm", "start-session",
        "--target", bastion_id,
        "--document-name", "AWS-StartPortForwardingSessionToRemoteHost",
        "--parameters", f"host={eks_endpoint},portNumber=443,localPortNumber=8443",
        "--region", REGION,
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)


def launch_ssm_rds(bastion_id, env):
    return subprocess.Popen([
        "aws", "ssm", "start-session",
        "--target", bastion_id,
        "--document-name", "AWS-StartPortForwardingSessionToRemoteHost",
        "--parameters", f"host={RDS_HOST},portNumber={RDS_PORT},localPortNumber={RDS_LOCAL}",
        "--region", REGION,
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)


def launch_port_forward(res, local_port, remote_port, env):
    return subprocess.Popen(
        ["kubectl", "port-forward", res, f"{local_port}:{remote_port}", "-n", NAMESPACE],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
    )


def main():
    print("=== RESTART TUNNELS & PORT-FORWARDS (WITH AUTO-HEALING WATCHDOG) ===\n")
    env = os.environ.copy()

    print("[1] Resolving Bastion & EKS endpoint ...")
    bastion_id, eks_endpoint = get_bastion_and_endpoint()
    print(f"    Bastion  : {bastion_id}")
    print(f"    EKS API  : {eks_endpoint}")

    # ── SSM EKS API Tunnel (8443) ────────────────────────────
    print("\n[2] Launching SSM EKS API Tunnel -> localhost:8443 ...")
    ssm_eks = launch_ssm_eks(bastion_id, eks_endpoint, env)
    print(f"    PID: {ssm_eks.pid} — Waiting 5s for tunnel to come up ...")
    time.sleep(5)

    # ── SSM RDS Tunnel (5433) ────────────────────────────────
    print(f"\n[3] Launching SSM RDS Tunnel -> localhost:{RDS_LOCAL} ...")
    ssm_rds = launch_ssm_rds(bastion_id, env)
    print(f"    PID: {ssm_rds.pid}")

    # ── Update kubeconfig ────────────────────────────────────
    print("\n[4] Updating kubeconfig -> https://localhost:8443 ...")
    subprocess.run(
        ["aws", "eks", "update-kubeconfig", "--name", CLUSTER_NAME, "--region", REGION],
        check=False, capture_output=True,
    )
    cluster_arn = f"arn:aws:eks:{REGION}:{ACCOUNT_ID}:cluster/{CLUSTER_NAME}"
    subprocess.run(
        ["kubectl", "config", "set-cluster", cluster_arn,
         "--server=https://localhost:8443", "--insecure-skip-tls-verify=true"],
        check=False, capture_output=True,
    )
    time.sleep(2)

    # ── kubectl port-forwards ────────────────────────────────
    print("\n[5] Launching kubectl port-forwards ...")
    pf_procs = {}
    for res, local_port, remote_port in SERVICES:
        p = launch_port_forward(res, local_port, remote_port, env)
        pf_procs[(res, local_port, remote_port)] = p
        print(f"    {res:45s} {local_port}:{remote_port}  PID={p.pid}")

    time.sleep(6)

    # ── Port connectivity check ──────────────────────────────
    print("\n[6] Port connectivity check:")
    for port in [7070, 7001, 9090, 3550, 8081, RDS_LOCAL]:
        status = "LISTENING" if check_port(port) else "FAILED"
        icon = "OK" if status == "LISTENING" else "!!"
        print(f"    [{icon}] localhost:{port:5d} -> {status}")

    print("\n[DONE] All services up. Auto-Healing Watchdog active — checking every 15s.")
    print("       Press Ctrl+C to stop all tunnels and port-forwards.\n")

    # ── Auto-Healing Watchdog loop ────────────────────────────
    procs_meta = {
        "ssm_eks": ("ssm_eks", None),
        "ssm_rds": ("ssm_rds", None),
    }
    for res, lp, rp in SERVICES:
        procs_meta[f"{res}:{lp}"] = ("pf", (res, lp, rp))

    active_procs = {
        "ssm_eks": ssm_eks,
        "ssm_rds": ssm_rds,
    }
    for (res, lp, rp), p in pf_procs.items():
        active_procs[f"{res}:{lp}"] = p

    try:
        while True:
            time.sleep(15)
            for name, p in list(active_procs.items()):
                if p.poll() is not None:
                    print(f"[WATCHDOG AUTO-HEAL] Process '{name}' (PID {p.pid}) died. Re-launching immediately...")
                    ptype, pmeta = procs_meta[name]
                    if ptype == "ssm_eks":
                        new_p = launch_ssm_eks(bastion_id, eks_endpoint, env)
                    elif ptype == "ssm_rds":
                        new_p = launch_ssm_rds(bastion_id, env)
                    elif ptype == "pf":
                        res, lp, rp = pmeta
                        new_p = launch_port_forward(res, lp, rp, env)
                    active_procs[name] = new_p
                    print(f"  ✅ Re-launched '{name}' -> New PID {new_p.pid}")
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Terminating all tunnels and port-forwards ...")
        for p in list(active_procs.values()):
            try:
                p.terminate()
            except Exception:
                pass
        print("[DONE] Cleaned up.")


if __name__ == "__main__":
    main()
