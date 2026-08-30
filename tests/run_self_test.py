"""Filter-sama 自测脚本（mock ctx，不依赖真实 Host）。

本脚本**不含任何硬编码绝对路径**，可随仓库复制到任意机器运行。

运行方式：
    # SDK 在常规位置时直接跑
    python plugins/filter_sama/tests/run_self_test.py

    # SDK 不在常规位置时，用环境变量指定
    MAIBOT_SDK_PATH="/path/to/maibot-plugin-sdk-2.7.0" \
        python plugins/filter_sama/tests/run_self_test.py

路径解析顺序：
    1. 插件根目录：相对本脚本自身位置推导，仓库搬到哪都能跑
    2. SDK 路径：环境变量 MAIBOT_SDK_PATH → 自动探测上级目录内的 maibot-plugin-sdk*
    3. 解释器：始终使用运行本脚本的 python，不写死路径
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Optional

# ── 路径自定位（零硬编码） ──────────────────────────────────────────────

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_NAME = PLUGIN_ROOT.name


def _discover_sdk() -> Optional[Path]:
    """定位 maibot-plugin-sdk 目录：环境变量优先，其次自动探测。"""
    env_value = os.environ.get("MAIBOT_SDK_PATH", "").strip()
    if env_value:
        candidate = Path(env_value).expanduser()
        if not candidate.is_dir():
            print(f"[warn] MAIBOT_SDK_PATH 指向的目录不存在，忽略: {candidate}")
        else:
            return candidate

    # 向上逐级查找 maibot-plugin-sdk*（取版本号最大的）
    root = PLUGIN_ROOT
    for _ in range(4):
        root = root.parent
        matches = [p for p in root.glob("maibot-plugin-sdk*") if p.is_dir()]
        if matches:
            return sorted(matches)[-1]
    return None


SDK_PATH = _discover_sdk()

if SDK_PATH is None:
    sys.exit(
        "未找到 maibot-plugin-sdk，无法运行自测。\n"
        "请任选一种方式：\n"
        "  1) 设置环境变量：MAIBOT_SDK_PATH=/path/to/maibot-plugin-sdk-2.7.0\n"
        "  2) 把 SDK 目录放在本插件目录的上级（或其再上级）目录中\n"
        f"  （当前插件根目录：{PLUGIN_ROOT}）"
    )

# SDK 目录 + 插件包的父目录入 sys.path（后者使 `import <PACKAGE_NAME>` 可用）
for path in (SDK_PATH, PLUGIN_ROOT.parent):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

print(f"插件根目录: {PLUGIN_ROOT}")
print(f"SDK 路径:   {SDK_PATH}\n")

from importlib import import_module  # noqa: E402  (需在 sys.path 就绪后导入)


def _resolve(module: Any, *names: str) -> Any:
    """按顺序解析模块中的符号，兼容插件改名历史。"""
    for name in names:
        obj = getattr(module, name, None)
        if obj is not None:
            return obj
    raise AttributeError(f"未在 {module.__name__} 中找到任一符号: {', '.join(names)}")


# ── mock ctx ───────────────────────────────────────────────────────────


class FakeLogger:
    """记录日志调用的假 logger。"""

    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    def log(self, level: int, msg: str) -> None:
        self.messages.append((level, msg))

    def debug(self, msg: str) -> None:
        self.log(logging.DEBUG, msg)

    def info(self, msg: str) -> None:
        self.log(logging.INFO, msg)

    def warning(self, msg: str) -> None:
        self.log(logging.WARNING, msg)

    def error(self, msg: str) -> None:
        self.log(logging.ERROR, msg)


class FakeCtx:
    """最小可用的 ctx 替身。"""

    def __init__(self) -> None:
        self.logger = FakeLogger()


# ── 测试辅助 ───────────────────────────────────────────────────────────


def make_plugin(overrides: dict[str, Any] | None = None) -> Any:
    """构造一个注入了 mock ctx 与配置的插件实例。"""
    config_mod = import_module(f"{PACKAGE_NAME}.config")
    plugin_mod = import_module(f"{PACKAGE_NAME}.plugin")

    plugin_cls = _resolve(plugin_mod, "FilterSamaPlugin", "OutputBlockerPlugin")
    settings_cls = _resolve(config_mod, "FilterSamaSettings", "OutputBlockerSettings")

    cfg_data: dict[str, Any] = {
        "plugin": {"enabled": True},
        "intercept": {
            "keywords": ["你好，我无法给到相关内容。"],
            "match_mode": "contains",
            "case_sensitive": False,
            "log_level": "warning",
        },
    }
    if overrides:
        for section, values in overrides.items():
            cfg_data.setdefault(section, {}).update(values)

    plugin = plugin_cls()
    plugin._set_context(FakeCtx())
    plugin._plugin_config_instance = settings_cls(**cfg_data)
    return plugin


def run_case(plugin: Any, kwargs: dict[str, Any], expected: str, label: str) -> None:
    """执行单个用例并断言 Hook 返回的 action。"""
    result = asyncio.run(plugin.intercept_outbound_message(**kwargs))
    action = result.get("action")
    status = "PASS" if action == expected else "FAIL"
    print(f"[{status}] {label}: action={action} (期望 {expected})")
    if status == "FAIL":
        raise AssertionError(f"{label}: 期望 {expected} 实际 {action}")


def _msg(message_id: str, text: str) -> dict[str, Any]:
    """构造 Hook kwargs 中的序列化 SessionMessage。"""
    return {"message_id": message_id, "processed_plain_text": text}


def _kwargs(message: dict[str, Any], stream_id: str = "stream") -> dict[str, Any]:
    return {
        "message": message,
        "stream_id": stream_id,
        "processed_plain_text": "",
    }


# ── 用例 ───────────────────────────────────────────────────────────────


def main() -> None:
    # 1. contains 命中（子串）→ abort
    p = make_plugin()
    run_case(
        p,
        _kwargs(_msg("m1", "好的~ 不过你好，我无法给到相关内容。抱歉"), "stream_a"),
        "abort",
        "contains 命中(子串)",
    )
    hits = [m for _, m in p.ctx.logger.messages if "命中过滤提示词" in m]
    assert hits, "未输出拦截日志"
    print(f"  -> 拦截日志已输出: {hits[0][:80]} ...")

    # 2. contains 未命中 → continue
    p = make_plugin()
    run_case(
        p,
        _kwargs(_msg("m2", "今天天气不错，我们出去走走吧"), "stream_a"),
        "continue",
        "contains 未命中放行",
    )

    # 3. 多条关键词，命中第二条 → abort
    p = make_plugin({"intercept": {"keywords": ["第一条", "第二条拦截词"]}})
    run_case(
        p,
        _kwargs(_msg("m3", "这是第二条拦截词出现的回复"), "stream_b"),
        "abort",
        "多关键词命中第二条",
    )

    # 4. exact 全文一致 → abort
    p = make_plugin(
        {"intercept": {"keywords": ["抱歉，我无法回答"], "match_mode": "exact"}}
    )
    run_case(
        p,
        _kwargs(_msg("m4", "抱歉，我无法回答"), "stream_c"),
        "abort",
        "exact 全文一致",
    )

    # 5. exact 部分包含但不完全一致 → continue
    p = make_plugin(
        {"intercept": {"keywords": ["抱歉，我无法回答"], "match_mode": "exact"}}
    )
    run_case(
        p,
        _kwargs(_msg("m5", "抱歉，我无法回答这个问题，但可以聊聊别的"), "stream_c"),
        "continue",
        "exact 部分包含放行",
    )

    # 6. regex 命中 → abort
    p = make_plugin(
        {
            "intercept": {
                "keywords": ["我(?:无法|不能|不方便)回答"],
                "match_mode": "regex",
            }
        }
    )
    run_case(
        p,
        _kwargs(_msg("m6", "关于这一点，我不能回答，抱歉"), "stream_d"),
        "abort",
        "regex 命中",
    )

    # 7. 忽略大小写 → 命中
    p = make_plugin(
        {
            "intercept": {
                "keywords": ["no response"],
                "match_mode": "contains",
                "case_sensitive": False,
            }
        }
    )
    run_case(
        p,
        _kwargs(_msg("m7", "Sorry, NO RESPONSE available"), "stream_e"),
        "abort",
        "忽略大小写命中",
    )

    # 8. 区分大小写 → 未命中放行
    p = make_plugin(
        {
            "intercept": {
                "keywords": ["no response"],
                "match_mode": "contains",
                "case_sensitive": True,
            }
        }
    )
    run_case(
        p,
        _kwargs(_msg("m8", "NO RESPONSE here"), "stream_e"),
        "continue",
        "区分大小写未命中",
    )

    # 9. 文本提取兜底（无 processed_plain_text，从 raw_message 组件提取）
    p = make_plugin()
    run_case(
        p,
        _kwargs(
            {
                "message_id": "m9",
                "raw_message": {
                    "components": [
                        {"type": "text", "text": "你好，我无法给到相关内容。"},
                        {"type": "text", "text": " 抱歉。"},
                    ]
                },
            },
            "stream_f",
        ),
        "abort",
        "raw_message 兜底提取命中",
    )

    # 10. 总开关关闭 → 放行
    p = make_plugin({"plugin": {"enabled": False}})
    run_case(
        p,
        _kwargs(_msg("m10", "你好，我无法给到相关内容。"), "stream_g"),
        "continue",
        "总开关关闭放行",
    )

    # 11. create_plugin 工厂函数可实例化
    plugin_mod = import_module(f"{PACKAGE_NAME}.plugin")
    plugin_cls = _resolve(plugin_mod, "FilterSamaPlugin", "OutputBlockerPlugin")
    instance = plugin_mod.create_plugin()
    assert instance is not None, "create_plugin() 返回空"
    assert isinstance(instance, plugin_cls), "工厂函数类型不符"
    print("[PASS] create_plugin() 工厂函数")

    print("\n全部用例通过 ✅")


if __name__ == "__main__":
    try:
        main()
    except AssertionError:
        traceback.print_exc()
        sys.exit(1)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
