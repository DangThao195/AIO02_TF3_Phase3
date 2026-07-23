"""
tools/registry.py — ToolRegistry + ToolSpec singleton

Đây là registry trung tâm cho toàn bộ tool metadata.
Mỗi tool file tự gọi ToolRegistry.register(spec, fn=tool_fn) ở module-level.
Planner (TGB) dùng get_all_schemas_text() để build prompt động.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("tools.registry")


@dataclass
class ToolSpec:
    """Metadata mô tả một tool — dùng để build planner prompt và validate."""
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    is_write: bool = False
    examples: list[dict] = field(default_factory=list)
    retry_config: dict = field(default_factory=lambda: {"max_retries": 1})


class ToolRegistry:
    """
    Singleton registry cho tất cả tool specs và implementations.

    Usage:
        # Trong mỗi tool file, sau khi define @tool:
        ToolRegistry.register(spec, fn=my_tool_fn)

        # Trong Planner (TGB):
        schema_text = ToolRegistry.get_all_schemas_text()
    """

    _specs: dict[str, ToolSpec] = {}
    _fns: dict[str, Any] = {}

    @classmethod
    def register(cls, spec: ToolSpec, fn: Any = None) -> None:
        """Đăng ký một ToolSpec (và optionally implementation fn) vào registry."""
        cls._specs[spec.name] = spec
        if fn is not None:
            cls._fns[spec.name] = fn
        logger.debug("[ToolRegistry] Registered: %s (write=%s)", spec.name, spec.is_write)

    @classmethod
    def get_spec(cls, name: str) -> Optional[ToolSpec]:
        """Lấy ToolSpec theo tên tool. Trả None nếu không tồn tại."""
        return cls._specs.get(name)

    @classmethod
    def get_fn(cls, name: str) -> Optional[Any]:
        """Lấy implementation function theo tên tool."""
        return cls._fns.get(name)

    @classmethod
    def get_all_specs(cls) -> dict[str, ToolSpec]:
        """Trả toàn bộ registry: {name: ToolSpec}."""
        return dict(cls._specs)

    @classmethod
    def get_all_schemas_text(cls) -> str:
        """
        Sinh text mô tả tất cả tools cho planner prompt.
        Format:
            Tool: tool_name
            Description: ...
            Input: {...}
            Output: {...}
            Write: true/false
            ---
        """
        if not cls._specs:
            return "(no tools registered)"

        lines: list[str] = []
        for name, spec in cls._specs.items():
            lines.append(f"Tool: {name}")
            lines.append(f"Description: {spec.description}")
            lines.append(f"Input: {json.dumps(spec.input_schema, ensure_ascii=False)}")
            lines.append(f"Output: {json.dumps(spec.output_schema, ensure_ascii=False)}")
            lines.append(f"Write: {'true' if spec.is_write else 'false'}")
            if spec.examples:
                ex = spec.examples[0]
                lines.append(f"Example: {json.dumps(ex, ensure_ascii=False)}")
            lines.append("---")

        return "\n".join(lines)

    @classmethod
    def clear(cls) -> None:
        """Xóa toàn bộ registry — dùng trong test."""
        cls._specs.clear()
        cls._fns.clear()
        logger.debug("[ToolRegistry] Cleared")

    @classmethod
    def is_write_tool(cls, name: str) -> bool:
        """Kiểm tra tool có phải write tool không."""
        spec = cls._specs.get(name)
        return spec.is_write if spec else False

    @classmethod
    def get_retry_config(cls, name: str) -> dict:
        """Lấy retry config của tool. Default: max_retries=1."""
        spec = cls._specs.get(name)
        if spec:
            return spec.retry_config
        return {"max_retries": 1}
