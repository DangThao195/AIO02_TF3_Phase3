FROM python:3.11-slim

WORKDIR /app

# Cài đặt curl để hỗ trợ liveness/readiness probe nếu cần
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy mã nguồn và cấu hình pyproject.toml
COPY pyproject.toml .
COPY src/ ./src/

# Cài đặt package cùng các dependency (bao gồm cả thư viện ML: scikit-learn, numpy)
RUN pip install --no-cache-dir .[ml]

# Cài đặt ASGI server uvicorn
RUN pip install --no-cache-dir uvicorn

# Tạo group và user non-root để tuân thủ Mandate 5 (Runtime Hardening)
RUN groupadd -g 10001 appuser && \
    useradd -r -u 10001 -g appuser appuser && \
    chown -R appuser:appuser /app

# Switch sang non-root user
USER 10001

# Copy toàn bộ file còn lại của dự án
COPY --chown=appuser:appuser . .

EXPOSE 8000

# Chạy server FastAPI lắng nghe trên cổng 8000
CMD ["python", "-m", "uvicorn", "ai_engine.server:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
