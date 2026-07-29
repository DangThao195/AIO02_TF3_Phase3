# HƯỚNG DẪN CHẠY & BẰNG CHỨNG NỘP BÀI AIOPS TF3 (MANDATE #22)

Thư mục `submit/` này chứa toàn bộ tài liệu đặc tả, bằng chứng và hướng dẫn nộp bài cho **AI MANDATE #22: Tự dập sự cố an toàn (Closed-Loop Auto-Mitigation)**.

---

## 📂 1. Cấu Trúc Thư Mục Nộp Bài
*   [MANDATE-22-CLOSED-LOOP-EVIDENCE.md](MANDATE-22-CLOSED-LOOP-EVIDENCE.md): Tài liệu Evidence Pack chi tiết về cơ chế phanh an toàn (Safety Gate), kiểm toán (Audit Log), hoàn tác (Rollback) và số liệu MTTD/MTTR cải thiện.
*   `AIOps/docs/MANDATE-22-CLOSED-LOOP-CHECKLIST.md`: Checklist DoD đầy đủ cho Mandate 22.
*   `AIOps/docs/MANDATE-07a-BENCHMARK-EVALUATION.md`: Báo cáo đối chứng so sánh Isolation Forest vs Burn Rate vs Hybrid.

---

## 🚀 2. Hướng Dẫn Chạy Kiểm Thử (Repro Steps)

### Bước 2.1: Chạy Unit & Integration Tests (197/197 Tests)
```bash
# Di chuyển vào thư mục code
cd AIOps/chaos-engine/ai-engine/

# Khởi tạo venv và cài đặt dependencies
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux

pip install -e .
pip install pytest pytest-asyncio

# Chạy test suite
pytest tests/
```

### Bước 2.2: Chạy Chaos Validation Scoreboard
Bơm tín hiệu sự cố offline mô phỏng để đánh giá độ nhạy phát hiện sự cố (Recall) và chẩn đoán nguyên nhân gốc (RCA Accuracy):
```bash
python scripts/chaos_validate.py
```
*Kết quả mong muốn: Recall đạt 100%, RCA Top-3 đạt 100%, 0 False Alarm.*

### Bước 2.3: Chạy Replay Dữ Liệu
Chạy replay dữ liệu lịch sử để đo đạc chỉ số MTTD trước và sau cải tiến:
```bash
python scripts/replay.py scenarios/mandate15-sample-set.json --baseline-mttd 900
```
*Kết quả mong muốn: MTTD đạt 30 giây (giảm 97.0% so với baseline 900 giây).*

---

## 🎫 3. Các Cách Nộp Bài Mẫu Trong Dự Án (Jira & PR Templates)

Trong dự án này, có 2 cách nộp bài chuẩn thường dùng để CDO/BTC chấm điểm:

### Cách 1: Nộp qua Jira Ticket (Bắt buộc theo Directive)
Tạo 1 Ticket trên hệ thống Jira với định dạng sau:
*   **Jira ID:** `AI MANDATE #22`
*   **Labels:** `ai-mandate`, `m22`
*   **Nội dung Comment:** Copy toàn bộ nội dung của tệp [MANDATE-22-CLOSED-LOOP-EVIDENCE.md](MANDATE-22-CLOSED-LOOP-EVIDENCE.md) dán vào phần bằng chứng.

### Cách 2: Nộp qua Pull Request (PR)
Tạo một Pull Request từ nhánh tính năng (`feat/DIRECTIVE-22`) vào nhánh chính (`main`) với mô tả tóm tắt sự thay đổi, các kết quả kiểm định tự động (Pytest, Chaos score, Replay) và link dẫn đến tài liệu evidence.
*(Đã được tạo tại: https://github.com/DangThao195/AIO02_TF3_Phase3/pull/3)*
