# 出站消息过滤器（Filter-sama）

MaiBot 出站消息过滤器。当麦麦的回复命中你配置的提示词时，**直接拦截不发送**，只在日志里留一条记录。可选开启 `/filter_test` 命令，跳过 planner 直接把消息喂给 reply 模型，用于联调验证整条过滤链路。

典型用途：模型偶尔会输出「你好，我无法给到相关内容。」这类无意义的拒答话术，与其让它发到群里，不如静默拦掉。

## 功能说明

- **静默拦截**：命中提示词的出站消息不会发送，也**不会写入聊天历史**。
- **三种匹配模式**：`contains`（包含，默认）/ `exact`（全文一致）/ `regex`（正则）。
- **多条提示词**：可配置任意数量，命中任意一条即拦截。
- **大小写控制**：默认忽略大小写；`regex` 模式下同样生效。
- **热重载**：改配置即时生效，无需重启 MaiBot。
- **可观测**：拦截事件按可配置级别写入日志，含 `message_id`、`stream_id` 和回复摘要。
- **直测命令**（可选）：`/filter_test <消息>` 跳过 planner 直连 reply 模型，生成结果同样经过拦截检查，可验证过滤是否生效。

## 工作原理

插件挂在 `send_service.after_build_message` 这个 Hook 上：

```
AI 生成回复 → SendService 构建出站消息
        ↓  after_build_message（Filter-sama 在此检查）
   命中 → {"action": "abort"} → 跳过 Platform IO、不写库、打日志
   未命中 → {"action": "continue"} → 正常发送
```

选这个 Hook 的原因：它是出站链上**最早的可 abort 控制点**，且主程序收到 `abort` 后直接 `return None`，连数据库都不写，所以聊天历史里不会留下被拦截内容的残骸。

**注意**：该 Hook 覆盖**所有**出站消息（AI 回复、主动发言、其他插件发出的消息），无法区分来源。提示词配得太宽会误伤正常消息。

## 安装

1. 把整个 `filter_sama/` 目录复制到 MaiBot 的 `plugins/` 目录下：
   ```
   MaiBot/
   └── plugins/
       └── filter_sama/
           ├── _manifest.json
           ├── plugin.py
           ├── config.py
           ├── __init__.py
           └── README.md
   ```
2. 启动 MaiBot，Runner 会依据 `config.py` 中的 `config_model` **自动生成** `config.toml`。
3. 在 WebUI 的插件管理里找到「出站消息过滤器（Filter-sama）」，确认可启用、配置可编辑。

> 仓库内**不包含** `config.toml`（已在 `.gitignore` 中忽略），因为它保存的是每个安装实例的运行时值，由 Runner 生成。

## 配置项

配置在 WebUI 插件管理中编辑，分三组。

### 插件设置（`[plugin]`）

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `enabled` | bool | `true` | 总开关。关闭后插件完全静默，所有出站消息正常发送 |
| `config_version` | str | `1.1.0` | 配置 schema 版本，请勿手动修改（WebUI 中隐藏） |

### 过滤规则（`[intercept]`）

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `keywords` | list[str] | `["你好，我无法给到相关内容。"]` | 命中即拦截的提示词列表，支持多条 |
| `match_mode` | `contains` / `exact` / `regex` | `contains` | 匹配模式 |
| `case_sensitive` | bool | `false` | 是否区分大小写 |
| `log_level` | `debug` / `info` / `warning` / `error` | `warning` | 拦截发生时的日志级别 |

三种模式的行为差异：

| 模式 | 提示词 | 回复 | 结果 |
|---|---|---|---|
| `contains` | `无法回答` | `抱歉，我无法回答` | 拦截 |
| `exact` | `抱歉，我无法回答` | `抱歉，我无法回答这个问题` | **放行**（要求全文一致） |
| `regex` | `我(?:无法\|不能)回答` | `关于这点，我不能回答` | 拦截 |

`regex` 模式下，非法正则会在日志中告警并跳过该条，不会导致插件崩溃。

### 直测命令（`[command]`）

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `enabled` | bool | `false` | 是否启用 `/filter_test` 命令。**默认关闭**，需要时在 WebUI 开启 |
| `model` | str | `replyer` | 调用 reply 输出使用的模型任务名（须存在于主程序 `model_config.toml` 的 `[model_task_config.*]`，加载时会校验并告警） |
| `default_prompt` | str | `请直接输出这句话：你好，我无法给到相关内容。` | `/filter_test` 不带参数时注入的默认 prompt（默认值可直接触发拦截词，方便联调） |
| `max_tokens` | int | `200` | 生成回复的最大 token 数 |
| `temperature` | float | `0.7` | 生成温度 |

## 命令

`/filter_test`（需先在配置中开启 `[command] enabled`）：

```
/filter_test <消息>
```

- **跳过 planner**：命令以 `intercept_message_level=2` 返回，阻止该消息继续走 Maisaka/planner，不会让 AI 再处理一遍。
- **操作员级别**：`permission="operator"`，只有 `[plugin].permission` 中配置的操作员（`platform:id`，如 `qq:123456789`）或 `command_permissions` 放行规则（`allow_users` / `allow_chats`）命中的用户/会话能触发，防止群内任意成员刷模型费用。1.2.0 起支持。
- **直连 reply 模型**：把 `<消息>` 作为 prompt 直接喂给 `command.model`（默认 `replyer`）生成文字。
- **生成结果同样经过过滤**：回复发出时仍会走 `after_build_message` 检查——命中拦截词就会被本插件拦下，日志里能看到拦截记录。这就是「测试」的意义。
- 不带参数时（`/filter_test`）回退到 `default_prompt`。

示例：`/filter_test 你好` → 「你好」喂给 reply 模型 → 生成回复 → 若命中拦截词则不发送，否则正常发送。

> 命令开启后注意：`/filter_test` 每次触发都会产生一次模型生成请求。默认仅操作员可触发；如需放行特定用户，在 `bot_config.toml` 的 `[plugin.command_permissions.com.valleywinds.filter-sama.filter_test]` 下配 `allow_users` / `allow_chats`。

## 权限 / 能力说明

`_manifest.json` 中 `capabilities` 声明为 `["send.text", "llm.generate", "llm.get_available_models"]`（与 SDK 能力注册表一致；`/filter_test` 命令开启后使用）：

- **过滤 Hook 本身零能力**：只调用 `self.ctx.logger` 写日志，不发送消息、不读数据库、不访问网络。
- **`/filter_test` 命令**（开启后）：`send.text` 发送生成的回复、`llm.generate` 调用 reply 模型、`llm.get_available_models` 校验任务名——三个能力与代码调用一一对应。
- Hook 处理器 `error_policy=ErrorPolicy.SKIP`：即使插件内部出错，也只跳过本次拦截，绝不阻断 MaiBot 主流程。
- 依赖：无第三方依赖，`dependencies` 为空，无需额外安装包。

## 故障排查

| 现象 | 排查方向 |
|---|---|
| 插件没出现在插件管理里 | 检查 `_manifest.json` 是否为合法 JSON；`id` / `version` / URL 格式是否合规；查看启动日志中的加载报错 |
| 配置了提示词但没拦住 | 确认 `[plugin] enabled = true`；确认匹配模式——`exact` 要求全文一致，`contains` 才做子串匹配 |
| 正常消息被误拦 | 提示词配太宽了。改用 `exact` 精确匹配，或用 `regex` 加锚点 `^...$` |
| `regex` 模式不生效 | 查看日志里是否有「拦截提示词不是合法正则，已跳过」告警，修正正则语法 |
| 改了配置没生效 | 配置热重载依赖 `on_config_update`，查看日志中是否有「[Filter-sama] 配置已热更新」；必要时重启 MaiBot |
| 想知道拦了什么 | 拦截记录按 `log_level` 写入日志，前缀 `[Filter-sama]`，含 `message_id`、`stream_id` 和回复摘要（截断 200 字） |
| `/filter_test` 没反应 | 确认 `[command] enabled = true`；确认你的账号在 `[plugin].permission` 操作员列表里（或命中 `command_permissions` 放行规则）；查看启动日志是否有「模型任务名 xxx 不存在」告警，用 `command.model` 改成存在的任务名 |
| `/filter_test` 报了「reply 生成失败」 | 查看日志中 `llm.generate 异常` 的具体原因；确认模型任务名与主程序配置一致 |
| 想确认拦截链路是否生效 | 开启 `[command] enabled` 后发 `/filter_test`（不带参数，用默认 prompt 触发拦截词），再看日志里是否有「命中过滤提示词」记录 |

## 许可证

GPL-3.0（GNU General Public License v3，与 `_manifest.json` 中的 `license` 字段一致，全文见仓库根目录 `LICENSE`）。

基于本插件修改或衍生的作品，必须以 GPL-3.0 发布源码，并保留原版权声明。
