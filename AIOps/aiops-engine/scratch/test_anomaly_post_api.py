import os
import sys
import time
import subprocess
import requests
import json

def test_api_locally():
    engine_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    venv_python = os.path.join(engine_dir, "venv", "Scripts", "python.exe")
    if not os.path.exists(venv_python):
        venv_python = "python"
        
    print("======================================================================")
    print("STARTING LOCAL FASTAPI SERVER FOR ISOLATION FOREST TESTING...")
    print("======================================================================")
    
    # Khởi chạy Uvicorn server ở background
    server_process = subprocess.Popen(
        [venv_python, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=engine_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    # Đợi 3 giây để server khởi động và nạp các model .joblib
    print("Waiting 3 seconds for server to start and load Isolation Forest models...")
    time.sleep(3.5)
    
    # URL endpoint dự đoán bất thường mới thêm vào
    url = "http://127.0.0.1:8000/anomaly/predict"
    
    # 1. Payload 1: Dữ liệu bình thường (RPS trung bình, CPU thấp, không lỗi)
    normal_payload = {
        "service": "frontend",
        "rps": 100.0,
        "cpu_usage": 0.35,
        "memory_usage": 0.50,
        "latency_p90": 0.05,
        "error_rate": 0.001
    }
    
    # 2. Payload 2: Lỗi Deploy bất thường (Error Rate 50%!)
    anomaly_payload = {
        "service": "frontend",
        "rps": 100.0,
        "cpu_usage": 0.35,
        "memory_usage": 0.50,
        "latency_p90": 0.05,
        "error_rate": 0.50  # Lỗi vọt cao!
    }
    
    # 3. Payload 3: Flash Sale hợp lệ (RPS vọt x5, CPU & Latency tăng cao, không lỗi)
    flashsale_payload = {
        "service": "frontend",
        "rps": 500.0,
        "cpu_usage": 0.88,
        "memory_usage": 0.75,
        "latency_p90": 0.40,
        "error_rate": 0.001  # Tải cực cao nhưng không có lỗi
    }
    
    headers = {"Content-Type": "application/json"}
    
    try:
        # TEST 1: Gửi request bình thường
        print("\nSending NORMAL traffic payload to frontend...")
        res_normal = requests.post(url, json=normal_payload, headers=headers, timeout=5)
        print(f"Response Status Code: {res_normal.status_code}")
        print("Response JSON:")
        print(json.dumps(res_normal.json(), indent=2))
        
        # TEST 2: Gửi request bất thường (INC-3 Deployment Error)
        print("\nSending ANOMALOUS traffic payload (50% Error Rate) to frontend...")
        res_anom = requests.post(url, json=anomaly_payload, headers=headers, timeout=5)
        print(f"Response Status Code: {res_anom.status_code}")
        print("Response JSON:")
        print(json.dumps(res_anom.json(), indent=2))
        
        # TEST 3: Gửi request Flash Sale tải cực đại (Kiểm tra xem đặc trưng ngữ cảnh giúp giảm FP thế nào)
        print("\nSending FLASH SALE traffic payload (500 RPS, High CPU, Low Errors) to frontend...")
        res_sale = requests.post(url, json=flashsale_payload, headers=headers, timeout=5)
        print(f"Response Status Code: {res_sale.status_code}")
        print("Response JSON:")
        print(json.dumps(res_sale.json(), indent=2))
        
    except Exception as e:
        print(f"\nERROR calling local API: {e}")
        
    finally:
        # Tắt server uvicorn
        print("\nTerminating local FastAPI server process...")
        server_process.terminate()
        try:
            server_process.wait(timeout=3)
            print("Server process successfully terminated.")
        except subprocess.TimeoutExpired:
            server_process.kill()
            print("Server process force-killed.")

if __name__ == "__main__":
    test_api_locally()
