"""Filter-sama 离线测试：真实 SDK、只假最外层 RPC 通道。

跑法（本地有任意可用 Python + maibot_sdk（源码仓库或已安装）即可，不需要 MaiBot 宿主）：

    PYTHONPATH=<maibot-plugin-sdk 仓库根> uv run --with pytest --with pydantic python -m pytest -q

覆盖：配置模型默认值、三种匹配模式、文本提取的组件类型过滤、出站拦截 Hook
的 abort / continue 语义、重试 Hook 的封顶逻辑、/filter_test 的拦截提示输出。
"""

import asyncio
import copy
import sys

import pytest
from maibot_sdk.context import PluginContext

PLUGIN_ID = "com.valleywinds.filter-sama"
INTERCEPTED_TEXT = "你好，我无法给到相关内容。"
DEFAULT_RETRY_REASON = "上一次回复未通过过滤检查，请重新生成一条不同的回复"

FULL_CONFIG = {
    "plugin": {"enabled": True, "config_version": "1.2.0"},
    "intercept": {
        "keywords": [INTERCEPTED_TEXT, "<thinking>"],
        "match_mode": "contains",
        "case_sensitive": False,
        "log_level": "debug",
        "retry_count": 2,
        "retry_reason": DEFAULT_RETRY_REASON,
    },
    "command": {
        "enabled": True,
        "model": "replyer",
        "default_prompt": "默认注入 prompt",
        "max_tokens": 200,
        "temperature": 0.7,
    },
}


def make_plugin(plugin_module, config=None):
    """创建插件实例并注入配置（无 ctx，纯配置态）。"""
    plugin = plugin_module.create_plugin()
    plugin.set_plugin_config(config if config is not None else copy.deepcopy(FULL_CONFIG))
    return plugin


def make_live_plugin(plugin_module, rpc_call):
    """创建带 ctx（假 RPC 通道）的插件实例，可跑 Hook / Command。"""
    plugin = make_plugin(plugin_module)
    plugin._set_context(PluginContext(PLUGIN_ID, rpc_call=rpc_call))
    return plugin


# ── 配置模型 ───────────────────────────────────────────────────────────

def test_config_defaults(plugin_module):
    """只注入 [plugin] 节时，业务节应落到默认值。"""
    plugin = make_plugin(plugin_module, {"plugin": {"config_version": "1.2.0"}})
    assert plugin.config.plugin.enabled is True
    assert plugin.config.intercept.retry_count == 2
    assert plugin.config.intercept.retry_reason == DEFAULT_RETRY_REASON
    assert plugin.config.intercept.match_mode == "contains"
    assert plugin.config.command.enabled is False
    assert plugin.config.command.model == "replyer"
    assert "你好，我无法给到相关内容。" in plugin.config.intercept.keywords


def test_config_schema_version(plugin_module):
    # CONFIG_SCHEMA_VERSION 定义在 config.py，随 plugin.py 的相对导入一并加载
    config_module = sys.modules["filter_sama.config"]
    assert config_module.CONFIG_SCHEMA_VERSION == "1.2.0"


# ── 匹配逻辑 ───────────────────────────────────────────────────────────

def test_match_keyword_contains(plugin_module):
    plugin = make_plugin(plugin_module)
    assert plugin._match_keyword(f"抱歉，{INTERCEPTED_TEXT}") == INTERCEPTED_TEXT
    assert plugin._match_keyword("正常回复") is None
    assert plugin._match_keyword("") is None


def test_match_keyword_case_insensitive(plugin_module):
    config = copy.deepcopy(FULL_CONFIG)
    config["intercept"]["keywords"] = ["<THINKING>"]
    plugin = make_plugin(plugin_module, config)
    assert plugin._match_keyword("前缀<thinking>后缀") == "<THINKING>"


def test_match_keyword_exact_requires_full_match(plugin_module):
    config = copy.deepcopy(FULL_CONFIG)
    config["intercept"]["match_mode"] = "exact"
    plugin = make_plugin(plugin_module, config)
    assert plugin._match_keyword(f"前后有字{INTERCEPTED_TEXT}") is None
    assert plugin._match_keyword(INTERCEPTED_TEXT) == INTERCEPTED_TEXT


def test_match_keyword_regex(plugin_module):
    config = copy.deepcopy(FULL_CONFIG)
    config["intercept"]["match_mode"] = "regex"
    config["intercept"]["keywords"] = ["无法.*相关"]
    plugin = make_plugin(plugin_module, config)
    assert plugin._match_keyword("关于这点，我无法给到相关内容") == "无法.*相关"
    assert plugin._match_keyword("我无法说明白这句话") is None  # 反向断言：正则不匹配即放行


def test_match_keyword_invalid_regex_is_skipped(plugin_module):
    config = copy.deepcopy(FULL_CONFIG)
    config["intercept"]["match_mode"] = "regex"
    config["intercept"]["keywords"] = ["([非法正则"]
    plugin = make_plugin(plugin_module, config)
    plugin._set_context(PluginContext(PLUGIN_ID, rpc_call=lambda *a, **k: None))
    assert plugin._match_keyword("任意文本") is None  # 非法正则跳过，不抛异常


# ── 文本提取 ───────────────────────────────────────────────────────────

def test_extract_text_prefers_processed_plain_text(plugin_module):
    plugin = make_plugin(plugin_module)
    kwargs = {
        "processed_plain_text": "顶层文本",
        "message": {"processed_plain_text": "消息内文本"},
    }
    assert plugin._extract_text(kwargs) == "顶层文本"


def test_extract_text_filters_non_text_components(plugin_module):
    """image / emoji 等组件的 data 是地址或结构化数据，不能当正文参与匹配。"""
    plugin = make_plugin(plugin_module)
    kwargs = {
        "message": {
            "raw_message": {
                "components": [
                    {"type": "image", "data": f"https://example.com/{INTERCEPTED_TEXT}.png"},
                    {"type": "text", "data": "正文内容"},
                ]
            }
        }
    }
    text = plugin._extract_text(kwargs)
    assert text == "正文内容"
    assert plugin._match_keyword(text) is None


# ── 出站拦截 Hook ──────────────────────────────────────────────────────

def _outbound_kwargs(text: str) -> dict:
    return {
        "message": {"message_id": "m1"},
        "processed_plain_text": text,
        "stream_id": "s1",
        "hook_name": "send_service.after_build_message",
    }


def test_outbound_hook_aborts_on_match(plugin_module):
    plugin = make_live_plugin(plugin_module, lambda *a, **k: None)
    result = asyncio.run(plugin.intercept_outbound_message(**_outbound_kwargs(INTERCEPTED_TEXT)))
    assert result == {"action": "abort"}


def test_outbound_hook_continues_on_clean_text(plugin_module):
    plugin = make_live_plugin(plugin_module, lambda *a, **k: None)
    result = asyncio.run(plugin.intercept_outbound_message(**_outbound_kwargs("正常回复")))
    assert result["action"] == "continue"


def test_outbound_hook_disabled(plugin_module):
    config = copy.deepcopy(FULL_CONFIG)
    config["plugin"]["enabled"] = False
    plugin = make_plugin(plugin_module, config)
    plugin._set_context(PluginContext(PLUGIN_ID, rpc_call=lambda *a, **k: None))
    result = asyncio.run(plugin.intercept_outbound_message(**_outbound_kwargs(INTERCEPTED_TEXT)))
    assert result["action"] == "continue"


# ── 重试 Hook ──────────────────────────────────────────────────────────

def _replyer_kwargs(text: str, retry_count: int = 0) -> dict:
    return {
        "response": text,
        "session_id": "s1",
        "retry_count": retry_count,
        "attempt": retry_count + 1,
        "hook_name": "maisaka.replyer.after_response",
    }


def test_retry_hook_requests_regeneration(plugin_module):
    plugin = make_live_plugin(plugin_module, lambda *a, **k: None)
    result = asyncio.run(plugin.retry_on_reply_response(**_replyer_kwargs(INTERCEPTED_TEXT)))
    assert result["action"] == "continue"
    modified = result["modified_kwargs"]
    assert modified["retry"] is True
    assert modified["retry_reason"] == DEFAULT_RETRY_REASON
    # 整体替换语义：全量 kwargs 必须原样带回（含 hook_name 与 Host 计数）
    assert modified["hook_name"] == "maisaka.replyer.after_response"
    assert modified["retry_count"] == 0


def test_retry_hook_stops_at_configured_limit(plugin_module):
    """配置 retry_count=2：Host 计数到 2 时不再请求重试，放行交由出站拦截兜底。"""
    plugin = make_live_plugin(plugin_module, lambda *a, **k: None)
    result = asyncio.run(plugin.retry_on_reply_response(**_replyer_kwargs(INTERCEPTED_TEXT, retry_count=2)))
    assert result == {"action": "continue"}


def test_retry_hook_retry_count_zero(plugin_module):
    config = copy.deepcopy(FULL_CONFIG)
    config["intercept"]["retry_count"] = 0
    plugin = make_plugin(plugin_module, config)
    plugin._set_context(PluginContext(PLUGIN_ID, rpc_call=lambda *a, **k: None))
    result = asyncio.run(plugin.retry_on_reply_response(**_replyer_kwargs(INTERCEPTED_TEXT)))
    assert result == {"action": "continue"}


def test_retry_hook_passes_clean_response(plugin_module):
    plugin = make_live_plugin(plugin_module, lambda *a, **k: None)
    result = asyncio.run(plugin.retry_on_reply_response(**_replyer_kwargs("正常回复")))
    assert result == {"action": "continue"}


def test_retry_hook_disabled(plugin_module):
    config = copy.deepcopy(FULL_CONFIG)
    config["plugin"]["enabled"] = False
    plugin = make_plugin(plugin_module, config)
    plugin._set_context(PluginContext(PLUGIN_ID, rpc_call=lambda *a, **k: None))
    result = asyncio.run(plugin.retry_on_reply_response(**_replyer_kwargs(INTERCEPTED_TEXT)))
    assert result == {"action": "continue"}


# ── /filter_test 命令 ──────────────────────────────────────────────────

def test_filter_test_outputs_hint_when_intercepted(plugin_module):
    """生成结果被自己的出站拦截 Hook 拦下时：补发「[已拦截]」并返回 (True, "[已拦截]", 2)。"""
    sent: list[str] = []
    send_calls = {"n": 0}

    async def fake_rpc(method, plugin_id, payload):
        assert method == "cap.call"
        capability = payload["capability"]
        if capability == "llm.generate":
            return {"success": True, "response": INTERCEPTED_TEXT, "reasoning": "", "model": "replyer"}
        if capability == "send.text":
            send_calls["n"] += 1
            sent.append(payload["args"]["text"])
            # 第一次发送：文本命中拦截词被 Hook 拦下 → send.text 返回 False；
            # 第二次发送「[已拦截]」：不命中拦截词 → 返回 True
            return {"success": send_calls["n"] > 1}
        raise AssertionError(f"unexpected capability: {capability}")

    plugin = make_live_plugin(plugin_module, fake_rpc)
    success, response, level = asyncio.run(
        plugin.cmd_filter_test(text="/filter_test 测试", stream_id="s1")
    )
    assert success is True
    assert response == "[已拦截]"
    assert level == 2
    assert sent == [INTERCEPTED_TEXT, "[已拦截]"]


def test_filter_test_passes_clean_reply(plugin_module):
    sent: list[str] = []

    async def fake_rpc(method, plugin_id, payload):
        capability = payload["capability"]
        if capability == "llm.generate":
            return {"success": True, "response": "正常回复", "reasoning": "", "model": "replyer"}
        if capability == "send.text":
            sent.append(payload["args"]["text"])
            return {"success": True}
        raise AssertionError(f"unexpected capability: {capability}")

    plugin = make_live_plugin(plugin_module, fake_rpc)
    success, response, level = asyncio.run(
        plugin.cmd_filter_test(text="/filter_test 测试", stream_id="s1")
    )
    assert success is True
    assert response == "reply 输出已发送"
    assert level == 2
    assert sent == ["正常回复"]


def test_filter_test_disabled(plugin_module):
    config = copy.deepcopy(FULL_CONFIG)
    config["command"]["enabled"] = False
    plugin = make_plugin(plugin_module, config)
    plugin._set_context(PluginContext(PLUGIN_ID, rpc_call=lambda *a, **k: None))
    success, response, level = asyncio.run(
        plugin.cmd_filter_test(text="/filter_test 测试", stream_id="s1")
    )
    assert success is False
    assert response == "命令未启用"
    assert level == 2


def test_filter_test_falls_back_to_default_prompt(plugin_module):
    prompts: list[str] = []

    async def fake_rpc(method, plugin_id, payload):
        assert method == "cap.call"
        capability = payload["capability"]
        if capability == "llm.generate":
            prompts.append(payload["args"]["prompt"])
            return {"success": True, "response": "正常回复", "reasoning": "", "model": "replyer"}
        if capability == "send.text":
            return {"success": True}
        raise AssertionError(f"unexpected capability: {capability}")

    plugin = make_live_plugin(plugin_module, fake_rpc)
    asyncio.run(plugin.cmd_filter_test(text="/filter_test", stream_id="s1"))
    assert prompts == ["默认注入 prompt"]


# ── 辅助函数 ───────────────────────────────────────────────────────────

def test_extract_arg(plugin_module):
    assert plugin_module.FilterSamaPlugin._extract_arg("/filter_test 你好呀") == "你好呀"
    assert plugin_module.FilterSamaPlugin._extract_arg("/filter_test") == ""
    assert plugin_module.FilterSamaPlugin._extract_arg("/filter_test  a  b") == "a  b"
    assert plugin_module.FilterSamaPlugin._extract_arg("") == ""


def test_coerce_int(plugin_module):
    assert plugin_module.FilterSamaPlugin._coerce_int("3") == 3
    assert plugin_module.FilterSamaPlugin._coerce_int(None, default=0) == 0
    assert plugin_module.FilterSamaPlugin._coerce_int("abc", default=7) == 7
