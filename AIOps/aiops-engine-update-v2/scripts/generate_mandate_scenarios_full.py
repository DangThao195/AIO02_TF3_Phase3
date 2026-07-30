"""
Bổ sung 5 kịch bản còn thiếu để có ĐỦ 9 kịch bản gốc trong implementation_plan.md
(SCN-A -> SCN-I), TẤT CẢ đều dùng phương pháp splice trên *_clean_baseline.csv THẬT
(baseline = 100% hành vi thật, chỉ khác cửa sổ incident) — khớp phân phối train.

Bảng đối chiếu ĐỦ 9 kịch bản (đã có 4, bổ sung 5):
  SCN-A  frontend          Node Drain / FP-resistance      -> TC1 (đã có, giữ nguyên)
  SCN-B  product-reviews   AI Spam DoS                      -> MỚI: RCB
  SCN-C  payment           Slow RAM Leak                    -> MỚI: RCC
  SCN-D  recommendation    HTTP 4xx Scan                    -> MỚI: RCD
  SCN-E  product-catalog   Network Packet Loss              -> MỚI: RCE
  SCN-F  checkout          Cascading Failure                -> TC3 (đã có, giữ nguyên)
  SCN-G  frontend          Thundering Herd (traffic thật)   -> MỚI: RCG (Ground Truth=NORMAL,
                                                                 dựa trên tương quan rps~latency
                                                                 THẬT đã verify = 0.83)
  SCN-H  shipping          Gradual SLO Erosion              -> TC4 (đã có, giữ nguyên)
  SCN-I  recommendation    CPU Steal / Noisy Neighbor        -> TC5 (đã có, giữ nguyên)
"""
import os
import sys
import numpy as np
import pandas as pd

engine_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(engine_dir)
from config import BENCHMARK_RANDOM_SEED

DATA_DIR = os.path.join(engine_dir, "datametric")
OUT_DIR = os.path.join(DATA_DIR, "realistic_test_cases")
os.makedirs(OUT_DIR, exist_ok=True)
rng = np.random.default_rng(BENCHMARK_RANDOM_SEED + 200)


def load_real_baseline(service):
    df = pd.read_csv(os.path.join(DATA_DIR, f"{service}_clean_baseline.csv"))
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df.reset_index(drop=True)


def save_case(df, name):
    path = os.path.join(OUT_DIR, f"{name}.csv")
    df.to_csv(path, index=False)
    print(f"  -> Saved {path} (n={len(df)}, anomaly_ticks={(df['label']==-1).sum()})")


# SCN-B: product-reviews — AI Spam DoS (RPS flood đa chiều + error_rate tăng do quá tải)
def build_rcb_product_reviews_ai_spam_dos():
    df = load_real_baseline("product-reviews")
    base_rps = df["rps"].quantile(0.5)
    start, window = len(df) // 2, 8  # 40 phút flood
    for i in range(window):
        j = start + i
        df.loc[j, "rps"] = base_rps * 12.0 + rng.normal(0, base_rps * 0.5)   # flood request
        df.loc[j, "error_rate"] = 0.25 + rng.normal(0, 0.01)                 # quá tải sinh lỗi
        df.loc[j, "client_error_rate"] = 0.10 + rng.normal(0, 0.01)          # rate-limit trả về
        df.loc[j, "label"] = -1
    save_case(df, "SCN-B_product-reviews_ai_spam_dos")


# SCN-C: payment — Slow RAM Leak (ramp tuyến tính dài ~2h, memory_usage vốn luôn =0 ở baseline)
def build_rcc_payment_slow_ram_leak():
    df = load_real_baseline("payment")
    start, window = len(df) // 2, 24  # 2 giờ, đúng đặc trưng "slow leak"
    for i in range(window):
        j = start + i
        ramp = (i + 1) / window
        df.loc[j, "memory_usage"] = 0.75 * ramp + rng.normal(0, 0.01)   # leak dần tới ngưỡng cao
        df.loc[j, "latency_p90"] = 1.8 * (1.0 + 2.0 * ramp) + rng.normal(0, 0.05)  # GC pause tăng dần
        df.loc[j, "label"] = -1
    save_case(df, "SCN-C_payment_slow_ram_leak")


# SCN-D: recommendation — HTTP 4xx Scan (client_error_rate tăng vọt, rps tăng nhẹ do bot quét)
def build_rcd_recommendation_http_4xx_scan():
    df = load_real_baseline("recommendation")
    base_rps = df["rps"].quantile(0.5)
    start, window = len(df) // 2, 10
    for i in range(window):
        j = start + i
        df.loc[j, "rps"] = base_rps * 1.8 + rng.normal(0, base_rps * 0.1)      # bot quét tăng nhẹ traffic
        df.loc[j, "client_error_rate"] = 0.30 + rng.normal(0, 0.02)            # hàng loạt 4xx
        df.loc[j, "label"] = -1
    save_case(df, "SCN-D_recommendation_http_4xx_scan")


# SCN-E: product-catalog — Network Packet Loss (client_error ngắt quãng + latency dao động mạnh)
def build_rce_product_catalog_network_packet_loss():
    df = load_real_baseline("product-catalog")
    start, window = len(df) // 2, 10
    for i in range(window):
        j = start + i
        # Packet loss KHÔNG liên tục đều — dao động mạnh giữa các tick (đặc trưng khác cascading)
        intermittent = 1.0 if i % 2 == 0 else 0.4
        df.loc[j, "client_error_rate"] = 0.18 * intermittent + rng.normal(0, 0.01)
        df.loc[j, "latency_p90"] = 3.0 * intermittent + rng.normal(0, 0.2)
        df.loc[j, "label"] = -1
    save_case(df, "SCN-E_product-catalog_network_packet_loss")


# SCN-G: frontend — Thundering Herd (Ground Truth = NORMAL, dựa trên tương quan rps~latency
#        THẬT đã verify = 0.83; tại top-5% rps thật, latency trung bình đã lên tới ~40ms)
def build_rcg_frontend_thundering_herd():
    df = load_real_baseline("frontend")
    p99_rps = df["rps"].quantile(0.99)   # ~69.6 (thật)
    start, window = len(df) // 2, 8      # 40 phút traffic dồn dập NHƯNG hợp lệ
    for i in range(window):
        j = start + i
        df.loc[j, "rps"] = p99_rps * 1.1 + rng.normal(0, p99_rps * 0.05)
        # Latency tăng theo ĐÚNG tỷ lệ quan hệ thật (corr=0.83, tại top-5% rps latency~40ms)
        df.loc[j, "latency_p90"] = 40.0 + rng.normal(0, 3.0)
        # label GIỮ NGUYÊN = 1 (Normal) — đây là traffic thật tăng đột biến, KHÔNG phải sự cố
    save_case(df, "SCN-G_frontend_thundering_herd")


if __name__ == "__main__":
    print("Generating 5 kịch bản còn thiếu để đủ 9 SCN-A..SCN-I (splice trên baseline thật)...")
    build_rcb_product_reviews_ai_spam_dos()
    build_rcc_payment_slow_ram_leak()
    build_rcd_recommendation_http_4xx_scan()
    build_rce_product_catalog_network_packet_loss()
    build_rcg_frontend_thundering_herd()
