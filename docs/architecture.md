# 开发文档（architecture）

> 本目录放**开发向文档**——贡献者与 AI 协作者看这里，README 面向用户，内容不要混。

## 模块结构

- `plugin.py` — 插件入口：`FilterSamaPlugin`（声明 `config_model`）、两个 `HookHandler`（重试层 + 出站拦截层）、一个 `Command`（`/filter_test`）、三个生命周期方法、匹配 / 文本提取 / 日志辅助函数
- `config.py` — 配置模型 `FilterSamaSettings`：`plugin`（总开关）/ `intercept`（过滤规则）/ `command`（直测命令）三节；`CONFIG_SCHEMA_VERSION` 随配置结构变更递增
- `_manifest.json` — manifest v2：能力声明 `send.text` / `llm.generate` / `llm.get_available_models`（HookHandler 无需声明能力）
- `__init__.py` — 包标记（重导出 `FilterSamaPlugin` / `create_plugin`；MaiBot 实际直接加载 `plugin.py`）
- `tests/` — pytest 离线测试：真实 SDK + 假 RPC 通道（`conftest.py` 隔离加载、`test_plugin.py` 覆盖配置默认值 / 三种匹配 / 组件过滤 / 出站拦截 / 重试封顶 / 命令输出）；跑法见 `tests/test_plugin.py` 头注释。⚠️ pytest 配置在 `tests/pytest.ini`——仓库根目录名含连字符（`Filter-sama`）不是合法包名，pytest 9 会把根目录当 Package 并在 setup 时导入其 `__init__.py` 导致相对导入炸掉；把 rootdir 锚在 `tests/` 可绕开。**不要把 pytest 配置挪回根 `pyproject.toml`**（根目录改名后可移回）
- `docs/` / `CHANGELOG.md` / `AGENTS.md` — 开发文档、用户可感知变更记录、给 AI 的仓库指令

## 数据流

### 拦截主链路（两层）

```
AI 生成回复（BaseMaisakaReplyGenerator.generate_reply_with_context）
   ↓  maisaka.replyer.after_response —— retry_on_reply_response（仅聊天回复链）
   命中且 kwargs.retry_count < [intercept].retry_count
        → {"action": "continue", "modified_kwargs": {**kwargs, "retry": True, "retry_reason": ...}}
        → Host 重新生成（被拒回复不发送、不进聊天历史，retry_reason 拼进下一轮【重生成约束】）
   命中但额度用尽 / 未命中 ↓
SendService 构建出站消息
   ↓  send_service.after_build_message —— intercept_outbound_message（全部出站消息）
   命中 → {"action": "abort"} → Host return None：跳过 Platform IO 发送、不写库
   未命中 → {"action": "continue"} → 正常发送
```

### /filter_test 链路

命令消息 → `_extract_arg` 取参数（空则回退 `default_prompt`）→ `ctx.llm.generate`（跳过 planner）→ `ctx.send.text` 发送 → 发送结果被自己的出站拦截 Hook 拦下（`send.text` 返回 False）时，补发一条「[已拦截]」。命令返回 `(True, response, 2)`，`intercept_message_level=2` 阻止该消息继续走 Maisaka/planner。

### 配置热重载链路

WebUI 保存配置 → `on_config_update(scope="self")` → `_compile_patterns()` 重编译 regex 缓存（contains / exact 模式不走缓存，直接读配置）。

## 设计取舍

- **为什么两层而不是只改一层**：`maisaka.replyer.after_response` 只覆盖聊天回复链，且该 Hook 不允许 abort（重试额度用尽后 Host 会放行最后一版回复）；`send_service.after_build_message` 允许 abort 且覆盖所有出站消息。前者做「挽救」，后者做「兜底」，缺一不可。
- **重试次数的控制方式**：Host 的重试计数是 `generate_reply_with_context` 循环内的局部变量（上限 `REPLYER_MAX_HOOK_RETRIES = 3`，硬编码），插件写回 `retry_count` / `max_retries` / `attempt` **不会被读取**（Host 1.3.15 源码核实）。插件唯一可控手段是按 kwargs 传入的 `retry_count`（已重试次数）与配置比较，逐次决定是否回带 `retry=True`。
- **`retry_reason` 留空语义**：Host 在 `retry_reason` 为空时重新生成但不追加约束句（纯重新采样）。默认值用中性文案而非「回复包含违禁内容」——因为拦截词覆盖不同质的失败模式（拒答话术的根因常在输入、思维链泄漏是格式问题），预设具体原因会误导模型。
- **`error_policy=ErrorPolicy.SKIP`**：两个 Hook 出错只跳过本次检查，绝不阻断 MaiBot 主流程。
- **文本提取按组件类型过滤**：出站拦截的 `_extract_text_from_components` 只取 `type == "text"` 组件，防止把 image / emoji 的 URL 当正文导致误拦。
- **兼容区间策略**：`host_application` 锁 `1.2.0 ~ 1.3.99`（同主次版本的更高补丁 Host 只 warning 不拒载；MaiBot 出新小线后实测再抬界），`sdk` 锁 `2.6.0 ~ 2.99.99`。不写 `999.999.999`。

## 能力与权限

- **capabilities 与调用一一对应**：`send.text`（`/filter_test` 发送生成结果与「[已拦截]」提示）、`llm.generate`（直测生成）、`llm.get_available_models`（加载时校验模型任务名）。两个过滤 / 重试 Hook 本身零能力，只写日志。
- **命令鉴权**：`/filter_test` 用 `permission="operator"`，操作员清单在主程序 `bot_config.toml` 的 `[plugin].permission`（格式 `platform:id`）；额外放行走 `[plugin.command_permissions.<插件id>.filter_test]` 的 `allow_users` / `allow_chats`。
- **`error_policy=ErrorPolicy.SKIP`**：两个 Hook 出错只跳过本次检查，绝不阻断 MaiBot 主流程。

## 给接手者（含 AI）的提示

- `[plugin].enabled` 是**宿主保留键**，配置模型里绝不能声明它（Host 用它做激活门禁，模型里再声明会出现冗余开关）。自研开关放业务节换名字。
- Hook 的 `modified_kwargs` 是**整体替换**不是逐键合并：回带时必须 `{**kwargs, ...}`，把 `hook_name` 等全键带回去。
- Host 在 `after_response` 之外还有两个内部强制重试分支（复古句号问话重生成、纯思考无正文重生成），与本插件的重试**共享同一个 `retry_count` 计数器**——极端情况下插件实际能争取到的重试次数会少于配置值。
- 命令返回的三元组第三项是 `intercept_message_level`（非 0 即拦截消息），不是「优先级」；`result[0]` 被 Host 忽略，Command 的回复必须自己 `ctx.send.text` 发。
- `llm.generate` 的 `system_prompt` 参数会被 Host 忽略（SDK 签名没有它）；本插件不需要 system prompt，未踩此坑，但改造时注意。
- `config.toml` 是运行时产物不入库；删除或新增配置字段时递增 `CONFIG_SCHEMA_VERSION`，旧部署缺新字段由 pydantic 默认值补齐。
- 官方文档与 SDK README 中「能力代理 17/18 种」等口径均落后于源码（实际 19 种），行为疑问一律以 SDK / 主程序源码为准。
