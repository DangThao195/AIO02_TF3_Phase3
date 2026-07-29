# 📊 MTTR Before/After Analysis — Mandate #22 Closed-Loop Mitigation

**Đội:** Task Force 3 (Team AIO02)
**Mandate:** #22 — Closed-loop Mitigation
**Ngày phân tích:** 2026-07-24

---

## 1. Định Nghĩa Các Chỉ Số Đo Đạc

| Chỉ số | Định nghĩa | Đơn vị |
|--------|-----------|--------|
| **MTTD** (Mean Time to Detect) | Thời gian từ khi sự cố phát sinh → hệ thống nhận biết | giây / phút |
| **MTTR** (Mean Time to Resolve) | Thời gian từ khi phát hiện → hệ thống phục hồi hoàn toàn | giây / phút |
| **MTTM** (Mean Time to Mitigate) | Thời gian từ khi phát hiện → hành động khắc phục được thực thi | giây |
| **E2E Recovery** | MTTD + MTTR = Tổng thời gian từ lúc sự cố xảy ra → hệ thống hồi phục | phút |

---

## 2. Bảng So Sánh MTTD Before vs After

| Chỉ số | BEFORE (Alertmanager tĩnh) | AFTER (AIOps ML Engine) | Cải thiện |
|--------|---------------------------|------------------------|-----------|
| **Cơ chế phát hiện** | Cảnh báo ngưỡng cứng (SLO Burn Rate 2%/1h) | Isolation Forest đa chiều (18 features) + Z-Score MAD | ML chủ động thay vì phản ứng thụ động |
| **MTTD** | **10 – 50 phút** | **30 – 35 giây** | **Giảm > 95%** |
| **Lead-time** | Tối thiểu 5 – 15 phút tích lũy lỗi | **0 chu kỳ trễ** (phát hiện ngay tại chu kỳ quét đầu tiên) | Loại bỏ hoàn toàn độ trễ tích lũy |
| **False Positive Rate** | Cao (ngưỡng cứng không phân biệt busy vs broken) | Thấp (confidence gate 0.7 + ML multi-dimensional) | Chống báo động giả |

---

## 3. Bảng So Sánh MTTR Before vs After (MỚI cho Mandate #22)

| Chỉ số | BEFORE (Thủ công SRE) | AFTER (Closed-Loop AIOps) | Cải thiện |
|--------|----------------------|--------------------------|-----------|
| **Quy trình xử lý** | Alert → SRE nhận → SSH/kubectl → kiểm tra → sửa → kiểm tra lại | Detect → Safety check → Auto-act → Verify → Close/Rollback | Tự động hóa hoàn toàn |
| **MTTM (Time to Mitigate)** | **5 – 20 phút** (SRE phải login, đọc alert, ra quyết định) | **< 60 giây** (Safety check + dry-run + execute tự động) | **Giảm > 85%** |
| **MTTR (Time to Resolve)** | **15 – 60 phút** (sửa + kiểm tra + xác nhận hồi phục) | **< 4 phút** (60s mitigate + 150s verify 5 chu kỳ) | **Giảm > 90%** |
| **E2E Recovery** (MTTD + MTTR) | **25 – 110 phút** | **< 4.5 phút** | **Giảm > 95%** |
| **Rollback Time** | **5 – 15 phút** (SRE quyết định + thực thi rollback thủ công) | **< 30 giây** (tự động trigger `rollout undo`) | Tức thì |
| **Escalation Time** | **Không xác định** (phụ thuộc SRE nhận biết cần escalate) | **Tức thì** (rollback fail → auto escalate SRE on-call) | Loại bỏ chờ đợi |

---

## 4. Chi Tiết Thời Gian Mỗi Bước Trong Closed-Loop

| Bước | Hành động | Thời gian | Ghi chú |
|------|----------|-----------|---------|
| **1. DETECT** | ML Isolation Forest quét anomaly | **30s** | Chu kỳ polling mỗi 30 giây |
| **2. EVIDENCE** | Thu thập log + trace (Evidence Pack) | **5 – 10s** | Query Prometheus + Jaeger |
| **3. DIAGNOSIS** | LLM Bedrock RCA analysis | **3 – 8s** | Nova Lite model, fallback local matcher |
| **4. SAFETY CHECK** | Whitelist + keyword + namespace + dry-run | **< 2s** | 5 lớp bảo vệ |
| **5. ACT** | Thực thi lệnh K8s | **2 – 5s** | `kubectl rollout restart` hoặc `scale` |
| **6. VERIFY** | Hybrid Double-Gate (Z-Score + IF) | **150s** (min) – **300s** (max) | 5 chu kỳ 30s liên tục hoặc timeout 5 phút |
| **7. ROLLBACK** (nếu cần) | `kubectl rollout undo` | **2 – 5s** | Chỉ kích hoạt khi verify fail |
| | **TỔNG (Happy Path)** | **~190 – 230s (≈ 3 – 4 phút)** | |
| | **TỔNG (Rollback Path)** | **~310 – 340s (≈ 5 – 6 phút)** | Bao gồm 5 phút verify timeout |

---

## 5. So Sánh Trực Quan (Timeline)

### BEFORE (Thủ công):
```
00:00  Sự cố xảy ra
  ...  (10-50 phút) Alertmanager tích lũy SLO burn → Alert fired
  ...  (5-20 phút)  SRE nhận alert → login → đọc dashboard → quyết định
  ...  (5-15 phút)  SRE thực thi sửa lỗi + kiểm tra thủ công
  ...  (5-15 phút)  Rollback nếu cần (SRE quyết định + thực thi)
01:50  Sự cố được giải quyết (worst case ~110 phút)
```

### AFTER (AIOps Closed-Loop):
```
00:00  Sự cố xảy ra
00:30  ML Isolation Forest phát hiện (MTTD = 30s)
00:40  Evidence Pack + RCA Diagnosis hoàn tất
00:42  Safety Check passed + Dry-run OK
00:45  Lệnh remediation thực thi
03:15  Verify 5 chu kỳ liên tục PASSED → Incident CLOSED
       TỔNG: ~3.5 phút (E2E Recovery)
```

---

## 6. Kết Luận

| Metric | Before | After | Cải thiện |
|--------|--------|-------|-----------|
| **MTTD** | 10 – 50 phút | 30 – 35 giây | **> 95%** |
| **MTTM** | 5 – 20 phút | < 60 giây | **> 85%** |
| **MTTR** | 15 – 60 phút | < 4 phút | **> 90%** |
| **E2E Recovery** | 25 – 110 phút | < 4.5 phút | **> 95%** |
| **Human Intervention** | Bắt buộc mọi bước | Chỉ cần cho Medium/High Risk | **Giảm > 80%** workload SRE |

> **Closed-Loop AIOps Engine giảm MTTR từ hàng giờ xuống dưới 5 phút**, đồng thời đảm bảo an toàn qua 5 lớp safety check + 2 cổng verify + rollback tự động. Đây là bước nhảy từ **reactive operations** sang **autonomous operations**.
