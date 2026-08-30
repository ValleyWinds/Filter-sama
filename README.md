# Filter-sama

MaiBot 出站消息过滤器。当麦麦的回复命中你配置的提示词时，**直接拦截不发送**，只在日志里留一条记录。

典型用途：模型偶尔会输出「你好，我无法给到相关内容。」这类无意义的拒答话术，与其让它发到群里，不如静默拦掉。

## 功能说明

- **静默拦截**：命中提示词的出站消息不会发送，也**不会写入聊天历史**。
- **三种匹配模式**：`contains`（包含，默认）/ `exact`（全文一致）/ `regex`（正则）。
- **多条提示词**：可配置任意数量，命中任意一条即拦截。
- **大小写控制**：默认忽略大小写；`regex` 模式下同样生效。
- **热重载**：改配置即时生效，无需重启 MaiBot。
- **可观测**：拦截事件按可配置级别写入日志，含 `message_id`、`stream_id` 和回复摘要。

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
3. 在 WebUI 的插件管理里找到「Filter-sama」，确认可启用、配置可编辑。

> 仓库内**不包含** `config.toml`（已在 `.gitignore` 中忽略），因为它保存的是每个安装实例的运行时值，由 Runner 生成。

## 配置项

配置在 WebUI 插件管理中编辑，分两组。

### 插件设置（`[plugin]`）

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `enabled` | bool | `true` | 总开关。关闭后插件完全静默，所有出站消息正常发送 |
| `config_version` | str | `1.0.0` | 配置 schema 版本，请勿手动修改（WebUI 中隐藏） |

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

## 命令

本插件**不提供任何命令**，也**不注册 Tool**：它是纯出站过滤器，不接收用户输入。

## 权限 / 能力说明

`_manifest.json` 中 `capabilities` 为**空数组**：

- 插件只调用 `self.ctx.logger` 写日志，**不发送消息、不读数据库、不访问网络**。
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

## 开发 / 测试

自测脚本不依赖真实 Host，用 mock ctx 注入配置，覆盖三种匹配模式、大小写、文本提取兜底、总开关、工厂函数：

```bash
# 方式一：SDK 在常规位置时直接跑
python plugins/filter_sama/tests/run_self_test.py

# 方式二：SDK 不在常规位置，用环境变量指定
MAIBOT_SDK_PATH="/path/to/maibot-plugin-sdk-2.7.0" \
  python plugins/filter_sama/tests/run_self_test.py
```

脚本会**自动定位**插件根目录（相对脚本自身位置），并依次探测环境变量 `MAIBOT_SDK_PATH` → 上级目录内的 `maibot-plugin-sdk*`；找不到时给出明确指引而不是静默失败。**脚本内无任何硬编码绝对路径。**

## 许可证

MIT（与 `_manifest.json` 中的 `license` 字段一致）。
