"""
Sinh 5 bộ Test Case "Realistic Incident" bằng cách SPLICE trực tiếp lên dữ liệu
*_clean_baseline.csv THẬT: giữ nguyên 100% các dòng baseline gốc, chỉ ghi đè giá trị
tại đúng cửa sổ thời gian xảy ra sự cố. Nhờ đó:

  - Hành vi "Normal" của test set = HÀNH VI THẬT 100% (không phải sinh bằng generator
    riêng biệt với quy mô traffic khác — đây chính là nguyên nhân khiến Precision ở tập
    synthetic cũ (generate_synthetic_data) sụp xuống ~4%: model học traffic thật (rps
    trung bình 0.1-6) rồi bị test trên traffic giả lập gấp ~200 lần).
  - Biên độ sự cố được hiệu chỉnh theo chính phân phối thật của từng service (dùng
    percentile p99/p100 thật của service đó làm mốc), không dùng con số áp đặt tùy ý.

5 kịch bản (bám theo đúng taxonomy trong implementation_plan.md, nhưng hiệu chỉnh quy mô
theo dữ liệu thật thay vì generator cũ):

  TC1  frontend        Transient 1-tick Noise Spike   (Ground Truth = NORMAL, test FP resistance)
  TC2  checkout        Sustained Latency+Error Incident (Ground Truth = ANOMALY, >=3 ticks)
  TC3  product-catalog + checkout   Cascading Failure (real edge trong services.json:
                                     checkout phụ thuộc product-catalog)
  TC4  shipping        Gradual SLO Erosion (ramp tuyến tính 24 ticks ~ 2 giờ)
  TC5  recommendation  Resource Exhaustion (CPU/Memory tăng dần, dùng đúng baseline
                                     cpu/memory thật vốn đã khác 0 của service này)
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

rng = np.random.default_rng(BENCHMARK_RANDOM_SEED)


def load_real_baseline(service: str) -> pd.DataFrame:
    path = os.path.join(DATA_DIR, f"{service}_clean_baseline.csv")
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df.reset_index(drop=True)


def pct(df, col, q):
    return float(df[col].quantile(q))


def save_case(df: pd.DataFrame, name: str):
    out_path = os.path.join(OUT_DIR, f"{name}.csv")
    df.to_csv(out_path, index=False)
    n_anom = int((df["label"] == -1).sum())
    print(f"  -> Saved {out_path} (n={len(df)}, anomaly_ticks={n_anom})")
    return out_path


# ---------------------------------------------------------------------------
# TC1: FRONTEND — Transient 1-Tick Noise Spike (Ground Truth = NORMAL)
# ---------------------------------------------------------------------------
def build_tc1_frontend_transient_noise():
    df = load_real_baseline("frontend")
    p99_lat = pct(df, "latency_p90", 0.99)
    idx = len(df) // 2  # 1 tick duy nhất, giữa dataset

    df.loc[idx, "latency_p90"] = p99_lat * 1.8   # blip đơn lẻ, không sustain
    df.loc[idx, "error_rate"] = 0.02
    # Ground Truth: đây KHÔNG phải incident thật -> label vẫn giữ nguyên = 1 (Normal)
    # (không đổi df.loc[idx, "label"])
    return save_case(df, "SCN-A_frontend_node_drain_fp_resistance")


# ---------------------------------------------------------------------------
# TC2: CHECKOUT — Sustained Latency + Error Incident (>=3 ticks liên tiếp)
# ---------------------------------------------------------------------------
def build_tc2_checkout_sustained_incident():
    df = load_real_baseline("checkout")
    p100_lat = pct(df, "latency_p90", 1.0)
    start = len(df) // 2
    window = 6  # 30 phút, đủ >= THREE_SIGMA_MIN_TICKS=2

    for i in range(window):
        j = start + i
        jitter = rng.normal(0, p100_lat * 0.03)
        df.loc[j, "latency_p90"] = p100_lat * 1.2 + jitter
        df.loc[j, "error_rate"] = 0.15 + rng.normal(0, 0.01)
        df.loc[j, "label"] = -1
    return save_case(df, "EXTRA-01_checkout_sustained_incident_generic")


# ---------------------------------------------------------------------------
# TC3: CASCADING FAILURE — product-catalog (root cause) -> checkout (symptom)
#      Cạnh thật theo services.json: "checkout": [..., "product-catalog", ...]
# ---------------------------------------------------------------------------
def build_tc3_cascading_failure():
    df_root = load_real_baseline("product-catalog")
    df_symptom = load_real_baseline("checkout")

    start = min(len(df_root), len(df_symptom)) // 2
    window = 8  # 40 phút

    p100_root_lat = pct(df_root, "latency_p90", 1.0)
    p99_symptom_lat = pct(df_symptom, "latency_p90", 0.99)

    for i in range(window):
        j = start + i
        # Root cause: product-catalog thật sự sập — ĐA CHIỀU cùng lúc (không chỉ latency+error
        # đơn lẻ), mô phỏng đúng hành vi thật của một service bị treo: latency vọt, error tăng,
        # client cũng nhận lỗi (circuit breaker), VÀ rps tụt hẳn vì service không xử lý kịp
        # request mới (stall) — đủ đa chiều để IsolationForest cô lập được qua nhiều feature
        # cùng lúc thay vì chỉ dựa vào 1-2 chiều dễ bị 16 chiều còn lại "trung hòa".
        df_root.loc[j, "latency_p90"] = p100_root_lat * 2.5 + rng.normal(0, p100_root_lat * 0.05)
        df_root.loc[j, "error_rate"] = 0.20 + rng.normal(0, 0.01)
        df_root.loc[j, "client_error_rate"] = 0.08 + rng.normal(0, 0.005)
        df_root.loc[j, "rps"] = df_root["rps"].quantile(0.5) * 0.15  # service stall: rps tụt còn ~15% median
        df_root.loc[j, "label"] = -1

        # Symptom: checkout chỉ bị ảnh hưởng lan truyền nhẹ hơn NHIỀU (không sập hẳn,
        # chỉ latency nhích lên do phải chờ product-catalog phản hồi chậm, kèm chút client error)
        df_symptom.loc[j, "latency_p90"] = p99_symptom_lat * 1.15 + rng.normal(0, p99_symptom_lat * 0.03)
        df_symptom.loc[j, "client_error_rate"] = 0.02 + rng.normal(0, 0.003)
        df_symptom.loc[j, "label"] = -1  # vẫn coi là lệch khỏi baseline thật (ground truth nhị phân)

    save_case(df_root, "SCN-F_product-catalog_ROOT_CAUSE_cascading_failure")
    save_case(df_symptom, "SCN-F_checkout_SYMPTOM_cascading_failure")
    return start, window  # trả về để script benchmark biết chính xác cửa sổ symptom


# ---------------------------------------------------------------------------
# TC4: SHIPPING — Gradual SLO Erosion (ramp tuyến tính ~2 giờ, 24 ticks)
# ---------------------------------------------------------------------------
def build_tc4_shipping_gradual_erosion():
    df = load_real_baseline("shipping")
    p99_lat = pct(df, "latency_p90", 0.99)
    start = len(df) // 2
    window = 24  # 2 giờ

    for i in range(window):
        j = start + i
        ramp_frac = (i + 1) / window  # 0 -> 1 tuyến tính
        # ĐA CHIỀU: latency + error + client_error cùng trôi dần theo cùng 1 ramp_frac,
        # mô phỏng đúng SLO erosion thật (mọi tín hiệu cùng xấu đi dần, không chỉ 1 chiều).
        df.loc[j, "latency_p90"] = p99_lat * (1.0 + 3.0 * ramp_frac) + rng.normal(0, p99_lat * 0.02)
        df.loc[j, "error_rate"] = 0.10 * ramp_frac + rng.normal(0, 0.002)
        df.loc[j, "client_error_rate"] = 0.05 * ramp_frac + rng.normal(0, 0.001)
        df.loc[j, "label"] = -1
    return save_case(df, "SCN-H_shipping_gradual_slo_erosion")


# ---------------------------------------------------------------------------
# TC5: RECOMMENDATION — Resource Exhaustion (CPU/Memory tăng dần, dùng đúng scale
#      cpu_usage/memory_usage THẬT vốn đã khác 0 của service này — không áp đặt số mới)
# ---------------------------------------------------------------------------
def build_tc5_recommendation_resource_exhaustion():
    df = load_real_baseline("recommendation")
    base_cpu = df["cpu_usage"].mean()      # ~0.019 (thật)
    base_mem = df["memory_usage"].mean()   # ~0.083 (thật)
    start = len(df) // 2
    window = 12  # 1 giờ

    base_lat_p95 = df["latency_p90"].quantile(0.95)
    for i in range(window):
        j = start + i
        ramp_frac = (i + 1) / window
        # ĐA CHIỀU: CPU/Memory tăng dần LÀ NGUYÊN NHÂN, latency/error tăng theo LÀ HỆ QUẢ
        # thật của resource exhaustion (đúng chuỗi nhân-quả thực tế, không chỉ đổi 1-2 chiều
        # rồi giữ nguyên 16 chiều còn lại — vốn khiến IsolationForest không đủ tín hiệu để
        # rút ngắn đường cô lập qua nhiều cây).
        df.loc[j, "cpu_usage"] = base_cpu * (1.0 + 9.0 * ramp_frac) + rng.normal(0, base_cpu * 0.05)
        df.loc[j, "memory_usage"] = base_mem * (1.0 + 6.0 * ramp_frac) + rng.normal(0, base_mem * 0.05)
        df.loc[j, "latency_p90"] = max(base_lat_p95, 1.0) * (1.0 + 8.0 * ramp_frac) + rng.normal(0, 0.2)
        if ramp_frac > 0.6:
            df.loc[j, "error_rate"] = 0.05 * (ramp_frac - 0.6) / 0.4 + rng.normal(0, 0.002)
        df.loc[j, "label"] = -1
    return save_case(df, "SCN-I_recommendation_cpu_steal")


def main():
    print("=" * 90)
    print(">>> GENERATING 5 REALISTIC INCIDENT TEST CASES (splice trên dữ liệu thật, seed cố định)")
    print("=" * 90)
    build_tc1_frontend_transient_noise()
    build_tc2_checkout_sustained_incident()
    build_tc3_cascading_failure()
    build_tc4_shipping_gradual_erosion()
    build_tc5_recommendation_resource_exhaustion()
    print("=" * 90)
    print("DONE. Test cases saved to:", OUT_DIR)


if __name__ == "__main__":
    main()
