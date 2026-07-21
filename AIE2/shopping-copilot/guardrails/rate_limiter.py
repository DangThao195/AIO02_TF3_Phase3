"""
Guardrail bổ sung: Rate Limiter — giới hạn request và token per user.

Chặn Case 5: Kẻ tấn công spam chatbot liên tục để cạn kiệt LLM token budget
hoặc làm sập Agent pod, vi phạm SLO.

Lưu ý khi deploy multi-replica:
    In-memory rate limiter này hoạt động PER-POD. Kẻ tấn công có thể bypass
    bằng cách hit nhiều pod. Nếu cần chính xác hơn, đổi sang Redis-based
    (dùng Valkey đang có sẵn trên cluster). Tuy nhiên, per-pod limiter vẫn
    bảo vệ được từng pod không bị quá tải — đủ tốt cho Phase 3.
"""

import time
import threading
import logging
from dataclasses import dataclass
from typing import Dict, List

logger = logging.getLogger("guardrails.rate_limiter")

# ── Cấu hình giới hạn ──
MAX_REQUESTS_PER_MINUTE = 10     # Tối đa 10 câu chat / phút / user
MAX_REQUESTS_PER_DAY = 200       # Tối đa 200 câu chat / ngày / user
MAX_ESTIMATED_TOKENS_PER_DAY = 50_000  # ~50K token / ngày / user (ước tính)

# Ước tính token trung bình per request (prompt + response)
AVG_TOKENS_PER_REQUEST = 250


@dataclass
class RateLimitResult:
    """Kết quả kiểm tra rate limit."""
    is_allowed: bool
    blocked_reason: str
    remaining_minute: int     # Số request còn lại trong phút hiện tại
    remaining_day: int        # Số request còn lại trong ngày
    estimated_tokens_used: int  # Ước tính token đã dùng hôm nay


class RateLimiter:
    """
    In-memory rate limiter theo user_id.

    Thread-safe (dùng Lock) để an toàn khi Agent xử lý nhiều request đồng thời.
    """

    def __init__(
        self,
        max_per_minute: int = MAX_REQUESTS_PER_MINUTE,
        max_per_day: int = MAX_REQUESTS_PER_DAY,
        max_tokens_per_day: int = MAX_ESTIMATED_TOKENS_PER_DAY,
    ):
        self.max_per_minute = max_per_minute
        self.max_per_day = max_per_day
        self.max_tokens_per_day = max_tokens_per_day
        self._lock = threading.Lock()

        # Lưu timestamps của mỗi request: {user_id: [timestamp1, timestamp2, ...]}
        self._requests: Dict[str, List[float]] = {}
        # Ước tính token đã dùng hôm nay: {user_id: total_tokens}
        self._daily_tokens: Dict[str, int] = {}
        # Ngày hiện tại để reset counter
        self._current_day: Dict[str, str] = {}

    def _get_today(self) -> str:
        return time.strftime("%Y-%m-%d")

    def _cleanup_old_requests(self, user_id: str, now: float):
        """Xóa các timestamp cũ hơn 24h để tránh memory leak."""
        if user_id in self._requests:
            cutoff_24h = now - 86400
            self._requests[user_id] = [
                ts for ts in self._requests[user_id] if ts > cutoff_24h
            ]

    def check_rate_limit(self, user_id: str) -> RateLimitResult:
        """
        Kiểm tra xem user có vượt quá giới hạn không.

        Gọi hàm này TRƯỚC khi xử lý request.
        Nếu is_allowed=True → tiếp tục xử lý.
        Nếu is_allowed=False → trả thông báo blocked cho user ngay.
        """
        now = time.time()
        today = self._get_today()

        with self._lock:
            # Khởi tạo nếu user mới
            if user_id not in self._requests:
                self._requests[user_id] = []

            # Reset counter hàng ngày
            if self._current_day.get(user_id) != today:
                self._current_day[user_id] = today
                self._daily_tokens[user_id] = 0
                # Xóa request cũ hơn 24h
                self._cleanup_old_requests(user_id, now)

            requests = self._requests[user_id]

            # ── Check 1: Request per minute ──
            one_minute_ago = now - 60
            recent_requests = [ts for ts in requests if ts > one_minute_ago]
            if len(recent_requests) >= self.max_per_minute:
                logger.warning(
                    f"[RATE_LIMIT] BLOCKED_MINUTE | user={user_id} | "
                    f"count={len(recent_requests)}/{self.max_per_minute}"
                )
                return RateLimitResult(
                    is_allowed=False,
                    blocked_reason=f"Bạn đã gửi quá {self.max_per_minute} tin nhắn trong 1 phút. "
                                   f"Vui lòng chờ một chút rồi thử lại.",
                    remaining_minute=0,
                    remaining_day=max(0, self.max_per_day - len(requests)),
                    estimated_tokens_used=self._daily_tokens.get(user_id, 0),
                )

            # ── Check 2: Request per day ──
            today_start = now - (now % 86400)  # Midnight UTC
            today_requests = [ts for ts in requests if ts > today_start]
            if len(today_requests) >= self.max_per_day:
                logger.warning(
                    f"[RATE_LIMIT] BLOCKED_DAY | user={user_id} | "
                    f"count={len(today_requests)}/{self.max_per_day}"
                )
                return RateLimitResult(
                    is_allowed=False,
                    blocked_reason=f"Bạn đã đạt giới hạn {self.max_per_day} tin nhắn trong ngày. "
                                   f"Vui lòng quay lại vào ngày mai.",
                    remaining_minute=0,
                    remaining_day=0,
                    estimated_tokens_used=self._daily_tokens.get(user_id, 0),
                )

            # ── Check 3: Token budget per day ──
            current_tokens = self._daily_tokens.get(user_id, 0)
            if current_tokens >= self.max_tokens_per_day:
                logger.warning(
                    f"[RATE_LIMIT] BLOCKED_TOKEN_BUDGET | user={user_id} | "
                    f"tokens={current_tokens}/{self.max_tokens_per_day}"
                )
                return RateLimitResult(
                    is_allowed=False,
                    blocked_reason="Bạn đã sử dụng hết ngân sách AI cho ngày hôm nay. "
                                   "Vui lòng quay lại vào ngày mai.",
                    remaining_minute=0,
                    remaining_day=0,
                    estimated_tokens_used=current_tokens,
                )

            # ── Cho phép — ghi nhận request ──
            requests.append(now)
            remaining_minute = self.max_per_minute - len(recent_requests) - 1
            remaining_day = self.max_per_day - len(today_requests) - 1

            return RateLimitResult(
                is_allowed=True,
                blocked_reason="",
                remaining_minute=max(0, remaining_minute),
                remaining_day=max(0, remaining_day),
                estimated_tokens_used=current_tokens,
            )

    def record_token_usage(self, user_id: str, tokens_used: int):
        """
        Ghi nhận token đã sử dụng SAU khi LLM trả response.

        Args:
            user_id:     ID người dùng.
            tokens_used: Số token thật (từ LLM usage) hoặc ước tính.
        """
        with self._lock:
            today = self._get_today()
            if self._current_day.get(user_id) != today:
                self._current_day[user_id] = today
                self._daily_tokens[user_id] = 0

            self._daily_tokens[user_id] = self._daily_tokens.get(user_id, 0) + tokens_used
            logger.info(
                f"[RATE_LIMIT] TOKEN_RECORDED | user={user_id} | "
                f"added={tokens_used} | total_today={self._daily_tokens[user_id]}"
            )


# ── Singleton instance — import và dùng ngay ──
rate_limiter = RateLimiter()
