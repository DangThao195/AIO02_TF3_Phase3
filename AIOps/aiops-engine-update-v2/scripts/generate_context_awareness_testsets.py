"""
TC6 & TC7: Kiểm chứng trực tiếp câu hỏi "gộp/không gộp service có ảnh hưởng tới khả năng
hiểu NGỮ CẢNH không?" — Trả lời: KHÔNG, ngữ cảnh (CPU tăng vì đông khách hay CPU tăng vì
sự cố) được capture bởi FEATURE SET (`cpu_per_rps`, `is_business_hours`,
`is_high_traffic_period`), độc lập hoàn toàn với việc có bao nhiêu model.

TC6 — Peak Hour Traffic Surge (Ground Truth = NORMAL): RPS và CPU cùng tăng TỶ LỆ THUẬN
      (giống giờ cao điểm thật) — nếu model hiểu ngữ cảnh, KHÔNG được báo động.
TC7 — Disproportionate CPU Spike (Ground Truth = INCIDENT): CPU tăng NHƯNG RPS đứng yên
      (vd memory leak / process bị treo, không liên quan traffic) — PHẢI được báo động.

Cả 2 dùng chung service `recommendation` (có cpu_usage/memory_usage thật khác 0), splice
trên baseline thật y hệt phương pháp TC1-TC5.
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
rng = np.random.default_rng(BENCHMARK_RANDOM_SEED + 100)


def load_real_baseline(service):
    df = pd.read_csv(os.path.join(DATA_DIR, f"{service}_clean_baseline.csv"))
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df.reset_index(drop=True)


def save_case(df, name):
    path = os.path.join(OUT_DIR, f"{name}.csv")
    df.to_csv(path, index=False)
    print(f"  -> Saved {path} (n={len(df)}, anomaly_ticks={(df['label']==-1).sum()})")


def build_tc6_peak_hour_proportional_surge():
    df = load_real_baseline("recommendation")
    base_rps = df["rps"].quantile(0.5)
    base_cpu = df["cpu_usage"].mean()
    base_mem = df["memory_usage"].mean()
    start = len(df) // 2
    window = 12  # 1 giờ "cao điểm"

    for i in range(window):
        j = start + i
        # RPS tăng 3x (giờ cao điểm thật) VÀ cpu/memory tăng ĐÚNG TỶ LỆ tương ứng
        # -> cpu_per_rps giữ nguyên, đây là hành vi HOÀN TOÀN BÌNH THƯỜNG.
        scale = 3.0
        df.loc[j, "rps"] = base_rps * scale + rng.normal(0, base_rps * 0.05)
        df.loc[j, "cpu_usage"] = base_cpu * scale + rng.normal(0, base_cpu * 0.05)
        df.loc[j, "memory_usage"] = base_mem * scale + rng.normal(0, base_mem * 0.05)
        # label GIỮ NGUYÊN = 1 (Normal) — đây KHÔNG phải incident, chỉ là giờ cao điểm
    save_case(df, "CTX-1_recommendation_peak_hour_context_normal")


def build_tc7_disproportionate_cpu_spike():
    df = load_real_baseline("recommendation")
    base_rps = df["rps"].quantile(0.5)
    base_cpu = df["cpu_usage"].mean()
    start = len(df) // 2
    window = 12

    for i in range(window):
        j = start + i
        # RPS ĐỨNG YÊN ở mức baseline thật (không phải giờ cao điểm), nhưng CPU vẫn tăng
        # 5x -> cpu_per_rps TĂNG VỌT (không giải thích được bởi traffic) -> ĐÂY MỚI LÀ INCIDENT
        # thật (vd memory leak, process bị treo, thread deadlock...).
        df.loc[j, "rps"] = base_rps + rng.normal(0, base_rps * 0.02)
        df.loc[j, "cpu_usage"] = base_cpu * 5.0 + rng.normal(0, base_cpu * 0.05)
        df.loc[j, "label"] = -1
    save_case(df, "CTX-2_recommendation_disproportionate_cpu_context_incident")


if __name__ == "__main__":
    print("Generating TC6 (context-normal peak hour) & TC7 (context-abnormal cpu spike)...")
    build_tc6_peak_hour_proportional_surge()
    build_tc7_disproportionate_cpu_spike()
