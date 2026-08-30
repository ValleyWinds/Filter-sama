"""Filter-sama —— 出站消息过滤器，配置模型。

分组：
- plugin: 插件总开关（enabled / config_version）
- intercept: 过滤规则（提示词列表、匹配模式、大小写、日志级别）
- command: /filter_test 直测命令（开关、reply 模型任务名、生成参数）

说明：本文件是配置结构与默认值的唯一来源（源码定义），
Runner 会在首次加载时依据它生成运行时的 config.toml，因此 config.toml 不需要入库。
"""

from __future__ import annotations

from typing import ClassVar, Literal

from maibot_sdk import Field, PluginConfigBase

# 配置 schema 版本；改动配置结构时递增，Runner 据此补齐新增字段
CONFIG_SCHEMA_VERSION = "1.1.0"


class PluginSectionConfig(PluginConfigBase):
    """插件基础配置。"""

    __ui_label__: ClassVar[str] = "插件设置"
    __ui_icon__: ClassVar[str] = "shield"
    __ui_order__: ClassVar[int] = 0

    config_version: str = Field(
        default=CONFIG_SCHEMA_VERSION,
        description="配置 schema 版本，请勿手动修改。",
        json_schema_extra={
            "disabled": True,
            "hidden": True,
            "label": "配置版本",
            "order": 99,
        },
    )
    enabled: bool = Field(
        default=True,
        description="是否启用出站过滤。关闭后插件完全静默，所有出站消息正常发送。",
        json_schema_extra={
            "label": "启用拦截",
            "hint": "关闭后插件完全静默，所有出站消息正常发送。",
            "order": 1,
        },
    )


class InterceptConfig(PluginConfigBase):
    """过滤规则配置。"""

    __ui_label__: ClassVar[str] = "拦截规则"
    __ui_icon__: ClassVar[str] = "filter"
    __ui_order__: ClassVar[int] = 1

    keywords: list[str] = Field(
        default_factory=lambda: ["你好，我无法给到相关内容。"],
        description="命中即拦截的提示词列表，支持多条。",
        json_schema_extra={
            "label": "拦截提示词",
            "hint": "当出站回复内容命中任一提示词时，该条消息将被拦截不发送。可配置多条，每行一条。",
            "order": 1,
        },
    )
    match_mode: Literal["contains", "exact", "regex"] = Field(
        default="contains",
        description="匹配模式：contains=包含匹配，exact=全文一致，regex=正则匹配",
        json_schema_extra={
            "label": "匹配模式",
            "hint": "contains：回复中包含提示词即拦截；exact：回复与提示词完全一致才拦截；regex：按正则表达式匹配。",
            "order": 2,
        },
    )
    case_sensitive: bool = Field(
        default=False,
        description="匹配时是否区分大小写（默认忽略大小写）。",
        json_schema_extra={
            "label": "区分大小写",
            "hint": "关闭时 hello 与 Hello 视为相同。regex 模式下该选项同样生效。",
            "order": 3,
        },
    )
    log_level: Literal["debug", "info", "warning", "error"] = Field(
        default="warning",
        description="拦截发生时使用的日志级别。",
        json_schema_extra={
            "label": "日志级别",
            "hint": "拦截发生时以该级别写入日志，便于在日志中查看拦截记录。",
            "order": 4,
        },
    )


class CommandConfig(PluginConfigBase):
    """/filter_test 直测命令配置。"""

    __ui_label__: ClassVar[str] = "直测命令"
    __ui_icon__: ClassVar[str] = "terminal"
    __ui_order__: ClassVar[int] = 2

    enabled: bool = Field(
        default=False,
        description="是否启用 /filter_test 命令。关闭后命令不生效，消息正常走 planner。",
        json_schema_extra={
            "label": "启用 /filter_test",
            "hint": "关闭后 /filter_test 命令不生效，消息正常走 planner。默认关闭，请按需开启。",
            "order": 1,
        },
    )
    model: str = Field(
        default="replyer",
        description="调用 reply 输出使用的模型任务名（对应主程序 model_task_config 中的任务名，如 replyer/planner/utils）",
        json_schema_extra={
            "label": "模型任务名",
            "hint": "必须是主程序 model_config.toml 的 [model_task_config.*] 中存在的任务名。回复模型任务默认是 replyer；加载时插件会校验并告警。",
            "order": 2,
        },
    )
    default_prompt: str = Field(
        default="请直接输出这句话：你好，我无法给到相关内容。",
        description="命令无附加参数时注入 reply 的默认 prompt",
        json_schema_extra={
            "label": "默认注入 prompt",
            "hint": "/filter_test 不带参数时使用。默认值可直接触发拦截提示词，方便联调验证过滤链路。",
            "order": 3,
        },
    )
    max_tokens: int = Field(
        default=200,
        description="生成回复的最大 token 数",
        json_schema_extra={
            "label": "最大 token",
            "hint": "控制输出长度，默认 200。",
            "order": 4,
        },
    )
    temperature: float = Field(
        default=0.7,
        description="生成温度",
        json_schema_extra={
            "label": "温度",
            "hint": "越高越随机，默认 0.7。",
            "order": 5,
        },
    )


class FilterSamaSettings(PluginConfigBase):
    """Filter-sama 插件完整配置。"""

    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    intercept: InterceptConfig = Field(default_factory=InterceptConfig)
    command: CommandConfig = Field(default_factory=CommandConfig)
