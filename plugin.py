"""Filter-sama —— 出站消息过滤器，插件入口。

当出站消息（AI 回复、主动发言、其他插件消息）命中用户配置的提示词时，
在 `send_service.after_build_message` Hook 点直接中止发送，并在日志中记录。

为什么选这个 Hook：
- `send_service.after_build_message` 是出站消息构建完成的第一个控制点，
  kwargs 含序列化 SessionMessage（`message`）、`processed_plain_text`、
  `stream_id` 等，且该 Hook 允许 abort。
- 主程序收到 abort 后直接 `return None`，跳过 Platform IO 发送，也不写库，
  即“拦截不发送”且不留聊天历史。

边界（不越权）：
- 只做“拦截 + 日志”，不修改消息内容，不发送替代消息。
- 拦截作用于所有出站消息，命中即拦，无法区分消息来源。
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from maibot_sdk import HookHandler, MaiBotPlugin
from maibot_sdk.types import ErrorPolicy, HookMode, HookOrder

# 兼容两种加载方式：
# - 作为包被 MaiBot 加载（__package__ 非空）→ 相对导入
# - 被测试脚本以顶层模块直接加载（__package__ 为空）→ 绝对导入
if __package__:
    from .config import FilterSamaSettings
else:  # pragma: no cover - 仅测试脚本走此分支
    from config import FilterSamaSettings

_LOG_LEVEL_MAP = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}


class FilterSamaPlugin(MaiBotPlugin):
    """Filter-sama 插件主类。

    生命周期：
    - on_load: 打印启动日志，预编译正则
    - on_unload: 清理正则缓存，打印卸载日志
    - on_config_update: 配置热更新（scope="self"）时重编译正则

    HookHandler:
    - send_service.after_build_message: BLOCKING 拦截，命中提示词即 abort
    """

    config_model = FilterSamaSettings

    def __init__(self) -> None:
        super().__init__()
        self._compiled_patterns: list[tuple[str, "re.Pattern[str]"]] = []

    # ── 生命周期 ───────────────────────────────────────────────────────

    async def on_load(self) -> None:
        """插件加载时执行：预编译正则缓存。"""
        self._compile_patterns()
        self.ctx.logger.info(
            f"[Filter-sama] 插件已加载: {len(self._get_keywords())} 条提示词, "
            f"模式={self._get_match_mode()}, "
            f"大小写={'区分' if self._is_case_sensitive() else '忽略'}"
        )

    async def on_unload(self) -> None:
        """插件卸载时执行：清理正则编译缓存。"""
        self._compiled_patterns.clear()
        self.ctx.logger.info("[Filter-sama] 插件已卸载")

    async def on_config_update(
        self, scope: str, config_data: dict[str, Any], version: str
    ) -> None:
        """配置热重载时执行：self.config 已自动刷新，重编译正则。"""
        del config_data
        if scope == "self":
            self._compile_patterns()
            self.ctx.logger.info(
                f"[Filter-sama] 配置已热更新: {len(self._get_keywords())} 条提示词, "
                f"模式={self._get_match_mode()}"
            )
        return None

    # ── HookHandler ────────────────────────────────────────────────────

    @HookHandler(
        "send_service.after_build_message",
        name="filter_sama_intercept",
        description="检测出站回复命中过滤提示词时中止发送",
        mode=HookMode.BLOCKING,
        order=HookOrder.EARLY,
        error_policy=ErrorPolicy.SKIP,
    )
    async def intercept_outbound_message(self, **kwargs: Any) -> dict[str, Any]:
        """出站消息构建完成后执行拦截检查。

        kwargs 关键字段：
        - message: 序列化 SessionMessage（含 processed_plain_text、message_id）
        - processed_plain_text: 可选的预处理纯文本内容
        - stream_id: 目标会话 ID

        命中任意提示词 → abort（不发送、不写库）+ 日志提示；未命中 → 放行。
        """
        if not self.config.plugin.enabled:
            return {"action": "continue", "modified_kwargs": kwargs}

        text = self._extract_text(kwargs)
        matched = self._match_keyword(text) if text else None
        if matched is None:
            return {"action": "continue", "modified_kwargs": kwargs}

        # 命中拦截：记录日志并中止发送
        stream_id = str(kwargs.get("stream_id") or "")
        message = kwargs.get("message") if isinstance(kwargs.get("message"), dict) else {}
        message_id = str(message.get("message_id") or "")
        self._log(
            f"[Filter-sama] 命中过滤提示词「{matched}」, 消息已拦截不发送 | "
            f"message_id={message_id or 'unknown'} | stream_id={stream_id or 'unknown'} | "
            f"回复内容: {self._truncate(text, 200)}"
        )
        return {"action": "abort"}

    # ── 匹配逻辑 ───────────────────────────────────────────────────────

    def _get_keywords(self) -> list[str]:
        """读取拦截提示词列表（防御旧配置格式）。"""
        try:
            keywords = self.config.intercept.keywords
        except Exception:
            keywords = None
        if not isinstance(keywords, list):
            return []
        return [str(k).strip() for k in keywords if k and str(k).strip()]

    def _get_match_mode(self) -> str:
        try:
            mode = self.config.intercept.match_mode
        except Exception:
            mode = None
        return mode if mode in ("contains", "exact", "regex") else "contains"

    def _is_case_sensitive(self) -> bool:
        try:
            return bool(self.config.intercept.case_sensitive)
        except Exception:
            return False

    def _compile_patterns(self) -> None:
        """预编译 regex 模式的提示词。"""
        self._compiled_patterns = []
        if self._get_match_mode() != "regex":
            return
        flags = 0 if self._is_case_sensitive() else re.IGNORECASE
        for kw in self._get_keywords():
            try:
                self._compiled_patterns.append((kw, re.compile(kw, flags=flags)))
            except re.error as exc:
                self.ctx.logger.warning(f"拦截提示词不是合法正则，已跳过: {kw} ({exc})")

    def _get_patterns(self) -> list[tuple[str, "re.Pattern[str]"]]:
        """获取 regex 编译缓存（惰性编译，配置热更新后自动重编译）。"""
        if self._get_match_mode() != "regex":
            return []
        if not self._compiled_patterns:
            self._compile_patterns()
        return self._compiled_patterns

    def _match_keyword(self, text: str) -> Optional[str]:
        """返回命中的提示词；未命中返回 None。"""
        if not text:
            return None
        mode = self._get_match_mode()
        case_sensitive = self._is_case_sensitive()
        normalized_text = text if case_sensitive else text.casefold()

        if mode == "exact":
            for kw in self._get_keywords():
                normalized_kw = kw if case_sensitive else kw.casefold()
                if normalized_text.strip() == normalized_kw.strip():
                    return kw
            return None

        if mode == "regex":
            for kw, pattern in self._get_patterns():
                if pattern.search(text):
                    return kw
            return None

        # contains（默认）
        for kw in self._get_keywords():
            normalized_kw = kw if case_sensitive else kw.casefold()
            if normalized_kw in normalized_text:
                return kw
        return None

    # ── 文本提取 ───────────────────────────────────────────────────────

    def _extract_text(self, kwargs: dict[str, Any]) -> str:
        """从 Hook kwargs 中提取出站消息的纯文本（三级兜底）。"""
        # 1. kwargs 顶层 processed_plain_text（SendService 显式传入）
        raw = kwargs.get("processed_plain_text")
        if isinstance(raw, str) and raw.strip():
            return raw

        # 2. 序列化 SessionMessage 的 processed_plain_text
        message = kwargs.get("message")
        if isinstance(message, dict):
            raw = message.get("processed_plain_text")
            if isinstance(raw, str) and raw.strip():
                return raw

            # 3. 兜底：从 raw_message 组件序列提取文本
            return self._extract_text_from_components(message.get("raw_message"))

        return ""

    def _extract_text_from_components(self, raw_message: Any) -> str:
        """从 raw_message（MessageSequence 序列化）中拼接文本组件。"""
        if isinstance(raw_message, dict):
            components = raw_message.get("components")
        elif isinstance(raw_message, list):
            components = raw_message
        else:
            return ""

        parts: list[str] = []
        if isinstance(components, list):
            for comp in components:
                if not isinstance(comp, dict):
                    continue
                # TextComponent 序列化后为 {"type": "text", "text": "..."}
                text_val = comp.get("text") or comp.get("data")
                if isinstance(text_val, str) and text_val.strip():
                    parts.append(text_val)
                elif isinstance(text_val, dict):
                    # DictComponent 自定义消息
                    inner = text_val.get("data")
                    if isinstance(inner, str) and inner.strip():
                        parts.append(inner)
        return " ".join(p for p in parts if p)

    # ── 日志 ───────────────────────────────────────────────────────────

    def _log(self, message: str) -> None:
        """按配置的日志级别输出过滤记录。"""
        try:
            configured_level = self.config.intercept.log_level
        except Exception:
            configured_level = None
        if configured_level not in _LOG_LEVEL_MAP:
            configured_level = "warning"
        self.ctx.logger.log(_LOG_LEVEL_MAP[configured_level], message)

    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        """截断文本用于日志展示。"""
        normalized = " ".join(text.split())
        if len(normalized) <= max_len:
            return normalized
        return normalized[:max_len] + "..."


def create_plugin() -> FilterSamaPlugin:
    """创建插件实例。"""
    return FilterSamaPlugin()
