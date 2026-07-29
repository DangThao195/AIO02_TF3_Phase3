import os
import subprocess
import time
import boto3
from dotenv import load_dotenv

# Tải toàn bộ cấu hình từ file .env
load_dotenv(override=True)

# Đọc cấu hình từ .env (Không hardcode bất kỳ tham số nào)
AWS_REGION = os.getenv("AWS_REGION", "ap-southeast-1")
EKS_NAMESPACE = os.getenv("EKS_NAMESPACE", "techx-tf3")
BASTION_TAG_NAME = os.getenv("BASTION_TAG_NAME", "techx-corp-tf3-bastion")

RDS_HOST = os.getenv("RDS_HOST", "techx-tf3-postgres.czwcs2ocww3q.ap-southeast-1.rds.amazonaws.com")
RDS_REMOTE_PORT = int(os.getenv("RDS_REMOTE_PORT", "5432"))
RDS_LOCAL_PORT = int(os.getenv("RDS_LOCAL_PORT", "5433"))

# Ánh xạ danh sách dịch vụ EKS từ tham số .env
kubectl_services = [
    ("deployment/product-catalog", int(os.getenv("PRODUCT_CATALOG_PORT", "3550")), 8080),
    ("deployment/cart", int(os.getenv("CART_PORT", "7070")), 8080),
    ("deployment/product-reviews", int(os.getenv("PRODUCT_REVIEWS_PORT", "9090")), 3551),
    ("deployment/recommendation", int(os.getenv("RECOMMENDATION_PORT", "8081")), 8080),
    ("deployment/currency", int(os.getenv("CURRENCY_PORT", "7001")), 8080),
    ("deployment/shipping", int(os.getenv("SHIPPING_PORT", "50051")), 8080),
]


def get_active_bastion_id() -> str:
    """Tra cứu Bastion Instance ID đang chạy dựa theo Tag Name trong file .env."""
    try:
        profile = os.environ.get("AWS_PROFILE", "default")
        session = boto3.Session(profile_name=profile)
        ec2 = session.client("ec2", region_name=AWS_REGION)
        res = ec2.describe_instances(
            Filters=[
                {"Name": "tag:Name", "Values": [BASTION_TAG_NAME]},
                {"Name": "instance-state-name", "Values": ["running"]},
            ]
        )
        for r in res.get("Reservations", []):
            for i in r.get("Instances", []):
                inst_id = i.get("InstanceId")
                if inst_id:
                    print(f"[BASTION] Tra cuu Bastion ID ({BASTION_TAG_NAME}) thanh cong: {inst_id}")
                    return inst_id
    except Exception as e:
        print(f"[BASTION] Loi tra cuu Bastion ID tu dong ({e}).")

    raise RuntimeError(f"Khong tim thay Bastion Instance dang running voi tag Name={BASTION_TAG_NAME}")


def main():
    print("=== STARTING EKS & RDS PORT FORWARDS (ENV CONFIG DRIVEN) ===")
    env = os.environ.copy()
    processes = []

    # 1. Dynamic Bastion ID lookup
    bastion_id = get_active_bastion_id()

    # 2. Setup EKS SSM API Tunnel (localhost:8443 -> EKS API Endpoint)
    try:
        cluster_name = os.getenv("EKS_CLUSTER_NAME", "techx-corp-tf3")
        account_id = os.getenv("AWS_ACCOUNT_ID", "197826770971")
        profile = os.environ.get("AWS_PROFILE", "default")
        session = boto3.Session(profile_name=profile)
        eks_client = session.client("eks", region_name=AWS_REGION)
        eks_desc = eks_client.describe_cluster(name=cluster_name)
        raw_endpoint = eks_desc["cluster"]["endpoint"]
        eks_endpoint = raw_endpoint.replace("https://", "")

        eks_ssm_cmd = [
            "aws", "ssm", "start-session",
            "--target", bastion_id,
            "--document-name", "AWS-StartPortForwardingSessionToRemoteHost",
            "--parameters", f"host={eks_endpoint},portNumber=443,localPortNumber=8443",
            "--region", AWS_REGION,
        ]
        print(f"Spawning SSM EKS API tunnel: localhost:8443 -> {eks_endpoint}:443 (via Bastion {bastion_id})")
        p_eks = subprocess.Popen(eks_ssm_cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        processes.append(p_eks)
        time.sleep(3)

        # Update kubeconfig
        print("Updating kubeconfig to use localhost:8443...")
        subprocess.run(["aws", "eks", "update-kubeconfig", "--name", cluster_name, "--region", AWS_REGION], check=False)
        cluster_arn = f"arn:aws:eks:{AWS_REGION}:{account_id}:cluster/{cluster_name}"
        subprocess.run(["kubectl", "config", "set-cluster", cluster_arn, "--server=https://localhost:8443", "--insecure-skip-tls-verify=true"], check=False)
    except Exception as e:
        print(f"Warning: Failed to setup SSM EKS API tunnel: {e}")

    # 3. Dynamic Bastion ID lookup cho SSM tunnel tới RDS Managed PostgreSQL
    rds_ssm_cmd = [
        "aws", "ssm", "start-session",
        "--target", bastion_id,
        "--document-name", "AWS-StartPortForwardingSessionToRemoteHost",
        "--parameters", f"host={RDS_HOST},portNumber={RDS_REMOTE_PORT},localPortNumber={RDS_LOCAL_PORT}",
        "--region", AWS_REGION,
    ]
    print(f"Spawning SSM RDS tunnel: localhost:{RDS_LOCAL_PORT} -> {RDS_HOST}:{RDS_REMOTE_PORT} (via Bastion {bastion_id})")
    try:
        p_rds = subprocess.Popen(rds_ssm_cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        processes.append(p_rds)
    except Exception as e:
        print(f"Failed to spawn SSM RDS tunnel: {e}")

    time.sleep(2)

    # 4. Kubectl port-forwards cho các microservices trên EKS
    for resource_path, local_port, target_port in kubectl_services:
        cmd = ["kubectl", "port-forward", resource_path, f"{local_port}:{target_port}", "-n", EKS_NAMESPACE]
        print(f"Spawning: {' '.join(cmd)}")
        try:
            p = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            processes.append(p)
        except Exception as e:
            print(f"Failed to spawn {resource_path}: {e}")

    # Special handling for shipping REST on port 50052
    try:
        cmd_shipping2 = ["kubectl", "port-forward", "deployment/shipping", "50052:8080", "-n", EKS_NAMESPACE]
        print(f"Spawning: {' '.join(cmd_shipping2)}")
        p_ship = subprocess.Popen(cmd_shipping2, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        processes.append(p_ship)
    except Exception as e:
        print(f"Failed to spawn shipping 50052: {e}")

    print("\nWaiting 5 seconds for connections to establish...")
    time.sleep(5)
    print("Background port forwards launched successfully!")
    print(f"RDS PostgreSQL available at localhost:{RDS_LOCAL_PORT} (via SSM tunnel to {bastion_id})")
    print("Giu terminal nay mo de duy tri ket noi. Nhan Ctrl+C de tat toan bo port-forward.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nTerminating all port forwards...")
        for p in processes:
            p.terminate()
        print("Cleaned up successfully.")


if __name__ == "__main__":
    main()

