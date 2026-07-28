import os
import sys
import time
import subprocess
import requests
import json

def run_local_e2e_flow():
    engine_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    venv_python = os.path.join(engine_dir, "venv", "Scripts", "python.exe")
    if not os.path.exists(venv_python):
        venv_python = "python"
        
    print("======================================================================")
    print("STARTING LOCAL FASTAPI SERVER FOR FULL E2E PIPELINE TESTING...")
    print("======================================================================")
    
    # Kích hoạt chế độ mô phỏng qua biến môi trường để chạy Sandbox
    env = os.environ.copy()
    env["AIOPS_SIMULATION_MODE"] = "true"
    
    server_process = subprocess.Popen(
        [venv_python, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=engine_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        text=True
    )
    
    # Hàm đọc và in log từ server không đồng bộ
    def print_server_logs(timeout_sec=5):
        start = time.time()
        # Đặt stdout non-blocking để không bị treo
        import msvcrt
        import win32api
        import win32con
        # Trên Windows, sử dụng select hoặc đọc luồng trơn tru
        os.set_blocking(server_process.stdout.fileno(), False)
        
        while time.time() - start < timeout_sec:
            try:
                line = server_process.stdout.readline()
                if line:
                    print(f"[SERVER] {line.strip()}")
            except Exception:
                pass
            time.sleep(0.1)
            
    # Đợi 5 giây cho ứng dụng khởi chạy
    time.sleep(5)
    print_server_logs(2)
    
    # 1. BƯỚC 1: Inject sự cố giả lập INC-3 (Lỗi deploy frontend)
    inject_url = "http://127.0.0.1:8000/simulate/inject?scenario=inc3"
    print(f"\n[CLIENT] STEP 1: Injecting INC-3 Incident (Frontend Bad Deployment)...")
    try:
        res = requests.post(inject_url, timeout=5)
        print(f"[CLIENT] Inject response: {res.json()}")
    except Exception as e:
        print(f"[CLIENT] Inject failed: {e}")
        server_process.terminate()
        return
        
    # 2. BƯỚC 2: Đợi Active Polling quét qua (chu kỳ 30s) và kích hoạt chẩn đoán
    print("\n[CLIENT] STEP 2: Waiting 35 seconds for Active Polling loop to trigger the E2E pipeline...")
    print("[CLIENT] You will see Jaeger RCA tracing, OpenSearch log collection, and Bedrock LLM diagnosing...")
    print_server_logs(35)
    
    # 3. BƯỚC 3: Approve tự động hành động khắc phục sự cố (Restart Frontend)
    approve_url = "http://127.0.0.1:8000/simulate/approve"
    print(f"\n[CLIENT] STEP 3: Sending Approval Action for the incident...")
    try:
        res_app = requests.post(approve_url, timeout=5)
        print(f"[CLIENT] Approval response: {res_app.json()}")
    except Exception as e:
        print(f"[CLIENT] Approval failed: {e}")
        
    # 4. BƯỚC 4: Đợi chạy lệnh Remediation và chạy Verification
    print("\n[CLIENT] STEP 4: Waiting 10 seconds for remediation command execution and verification...")
    print_server_logs(10)
    
    # Tắt server
    print("\n[CLIENT] Terminating local FastAPI server...")
    server_process.terminate()
    try:
        server_process.wait(timeout=3)
        print("[CLIENT] Server process successfully terminated.")
    except Exception:
        server_process.kill()
        print("[CLIENT] Server process force-killed.")

if __name__ == "__main__":
    run_local_e2e_flow()
