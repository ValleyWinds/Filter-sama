# AGENTS.md — 给在这个插件仓库工作的 AI

这是一个 MaiBot 插件仓库（Plugin SDK 2.x / Host 1.3.x）。任何 AI 助手在本仓库工作前先读完本文件。

## 权威参考（遇到疑问按此顺序查）

1. **本仓库 `docs/architecture.md`**：模块结构、数据流、设计取舍——改代码前先读它，改完同步它。
2. **SDK / MaiBot 主程序源码**：行为疑问的唯一真相。
3. **maibot-plugin-dev 技能**（https://github.com/ValleyWinds/maibot-plugin-dev ）：SDK 代理签名速查、组件规范、常见陷阱、发布收录规则——已逐行对照源码核对，**用作加速器而非最终答案**：它是快照，可能落后于你的环境；若其基线（SKILL.md 顶部基线行）低于当前 SDK / Host 版本、或所述与源码冲突，一律以源码为准。没装技能可直接克隆或浏览该仓库，`references/` 下全部是纯 Markdown。

## 开发规矩

- **配置**：`config.toml` 是首次运行按 `config.py` 自动生成的运行时产物，**不进 git**（`.gitignore` 已排除）；实机配置可能含 token，绝不提交。`[plugin].enabled` 是宿主保留键，配置模型里不要声明它。
- **版本区间**：`host_application` 上界锁已实测的次版本线（当前 `1.3.99`）、`sdk` 上界锁 `2.99.99`，都不要写 `999.999.999`。MaiBot 出新小线后先实测再抬界，并递增插件 `version` 发新版。
- **插件 `id` 发布后不得变更**；manifest 新增字段前先查技能的必填/禁写字段清单（manifest v2 是 `extra="forbid"`，写错字段直接拒载）。
- **验证**：本仓库无自动化测试（曾有，后按最简结构原则移除）。改了 `plugin.py` / `config.py` 至少跑 `python -m py_compile plugin.py config.py`；行为验证用本地 MaiBot 实例热加载（部署到实例 `plugins/` 目录，WebUI 重新加载即可，无需重启）。
- 文档一律简体中文。

## 发布规矩

- **固定流程**：改代码 → 更新 `_manifest.json` 的 `version`（严格三段式）→ commit → 打同版本 Tag（`v1.2.3` 或 `1.2.3` 均可）→ 基于 Tag 发 GitHub Release，**标题用纯版本号**（如 `v1.2.3`），预发布勾 Prerelease。
- **push 与发 Release 是两道独立审批**，均须仓库主人明确同意；同意 push 不等于同意发 Release。
- **README / Release Notes / CHANGELOG 等用户可见文案先在对话中出稿待审**，主人定稿后一次性 commit，不要每改一版就提交。
- **Release Notes 只写用户能感知的更新要点**：分「主要功能 / 细节」两部分、一个功能一行按模块分组；版本号提升与依赖更新不用写；SDK 版本、内部机制等维护者信息一律不进。写完同步 `CHANGELOG.md`（manifest `changelog` 字段指向它）。
- **README 面向用户**：安装指引主路径写「WebUI 插件市场一键安装」；不要写 SDK 安装步骤（SDK 由主程序自动提供）；效果示例必须实测取真，禁止凭印象编造。
- push 前过一遍防泄漏自查：`.env`、密钥、带用户名的本机路径、`data/`、`config.toml` 不得进仓库；`git log -p | grep -iE "key|token|secret|password"` 无命中再推。

## 红线（违反即错，无例外）

- **LICENSE 与原作者署名一条不能删**；更换协议必须遵守原协议规则（copyleft 不能换宽松协议洗白）。
- fork / 二次开发的改动**发布前先向原作者提 issue 或 PR**。
- **不得让用户修改 MaiBot 主程序源码来使用本插件**；确需主程序改动，先向官方提 issue 请求。
- 已收录的 Tag 不改写；修复一律发新版本号。
