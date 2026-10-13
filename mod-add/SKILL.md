---
name: mod-add
description: 为当前 CLI 添加和配置第三方模型子代理，自动识别 API 端点并适配调用方式。用户提到添加子代理、添加模型、第三方模型、中转站、/model、Gemini、图像模型时使用，命令为 /mod-add。
when-to-use: 添加子代理 添加模型 第三方模型 中转站 /model Gemini 图像模型
user-invocable: true
argument-hint: "[--video]"
license: MIT
---

# 添加子代理

先识别实际运行的 CLI，不按当前模型名推断。若在 Codex 中加载本文件，改读本文件真实路径对应的 [Codex 版](../codex/mod-add/SKILL.md)，或已安装的 `~/.agents/skills/mod-add/SKILL.md`；确认目标不是本文件后，按该版执行。找不到对应版本时提示安装，不执行下面的 Grok 流程。

命令：`/mod-add`

把中转站上的模型写进 `~/.grok/config.toml`，使 `/model` 能选到。中转站地址和密钥保存在本技能自动生成的本地连接文件中；用户也可以直接在对话中提供，由代理写入文件。真实密钥只写入连接文件和 `~/.grok/config.toml`，回复时不复述密钥。只追加 `[model.*]` 条目，`[models].default` 保持不变。

## 初次询问

状态文件：`~/.grok/skills/mod-add/state.json`。不提交进仓库。

文件不存在时先问，等回答再改配置：

> 要把中转站上还没进 `/model` 的第三方模型加进去吗？包含对话模型和图像模型。视频模型默认不加。

- 同意：写入 `{"asked":true,"add_models":true}`，然后添加。
- 拒绝：写入 `{"asked":true,"add_models":false}`。以后不再问，也不自动加。
- 用户之后说「添加模型」或运行本命令并要求添加：把 `add_models` 改成 `true` 再添加。

`add_models` 已是 `true` 时不再询问。只补配置里还没有的 id。参数含 `--video` 时才加入 id 里带 `video` 的模型。

## 连接配置（自动生成）

连接文件放在技能包主目录，即本技能 `mod-add` 目录的上一层。直接使用源码包时为 `mod-agent-skills/connection.json`；复制安装后为 `~/.grok/skills/connection.json`。用户同意添加后，由代理检查并在缺失时创建，不要让用户手动建文件。使用 JSON 序列化写入，将文件权限设为 `0600`，不提交进仓库。若新路径不存在且旧版 `~/.grok/skills/mod-add/connection.json` 已有配置，保留内容迁移到新路径；不覆盖新路径中的文件。

```json
{
  "base_url": "",
  "api_key": "",
  "models": {
    "read": "deepseek-flash",
    "write": "deepseek-v4-pro",
    "brain": "gpt-6-luna",
    "review": "grok-4.7"
  }
}
```

`models` 是与 Codex 版共用的初始角色映射，不代表服务一定提供这些 ID；添加 Grok 模型仍以实际服务信息为准。

- 文件已有完整配置时直接复用。用户明确提供新地址或密钥时，按其要求更新；不要用空模板覆盖已有值。
- 源码包中的连接文件可能与 Codex 版共用；更新地址、密钥时保留已有 `models` 等其他字段。
- 文件缺失或字段为空时，先使用用户本次提供的连接信息；否则可从 `~/.grok/config.toml` 已有第三方 `[model.*]` 条目复制。按 `(base_url, api_key)` 去重，只有一组完整连接时才自动采用；有多组时让用户指定，可展示地址和模型名，不展示密钥。
- 已有部分配置时保留非空字段，只从确认属于同一连接的条目补齐；无法匹配就让用户补齐，不用其他连接覆盖。
- 地址与密钥必须属于同一连接。同一 origin（协议、主机、端口）内规范化路径时继续使用当前密钥；用户更换服务时，没有提供配套密钥或明确要求沿用，就询问配套密钥，不自动把旧密钥发往新服务。
- 没有可用信息时仍先生成上述空文件，主动打开文件所在目录供用户编辑（macOS 使用 `open <目录绝对路径>`），并给出文件链接；打不开时说明实际错误和路径。用户也可直接在对话中提供，由代理代填。用户保存、补齐后重新读取文件，再继续添加，不在编辑期间覆盖文件。
- 文件无法解析时说明问题并保留原文件，不重建覆盖。`base_url` 和 `api_key` 都必须是非空字符串。地址可为域名入口、API 基础路径或完整端点，由代理识别和规范化；缺少连接信息或地址含账号、查询参数、片段时不请求接口、不追加模型配置。

## 自动识别端点与运行环境

1. 确认当前使用 Grok CLI，根据当前版本的帮助、配置说明或已有可用配置核实支持的 `api_backend` 及 `base_url` 拼接规则，不假设 Grok 会不会自动添加 `/v1`。基础路径由服务实际路由和客户端最终请求 URL 决定，不按 CLI 名称固定加删 `/v1`。Codex 环境应使用包内 `codex/mod-dispatch/scripts/relay.py` 调度，不向 Codex 配置复制 Grok 模型表。
2. 在内存中整理候选地址：无协议的域名入口先在用户指定的同一主机上补 HTTPS，不擅自降级 HTTP；去掉尾斜杠，识别并去掉末尾 `/models`、`/chat/completions` 或 `/responses`，保留前面的 `/v1`、`/api/...` 等自定义路径。由代理修正格式，不让用户手动补路径；完整端点只作为协议线索。
3. 使用同一连接的密钥请求候选基础地址下的 `GET /models`。裸入口的 `/models` 返回 404 时，再检查 `/v1/models`；不随意裁掉自定义路径。最多核对 3 个有依据的候选；401、403、429 按认证、权限或限流处理，不当作路径错误乱试。不跨 origin 发密钥，不跟随重定向转发密钥，不为探测写临时配置。
4. 确认列表响应有效后，在连接文件保存服务已确认的 API 基础路径，保留其他字段。写 Grok 模型配置时再按该 CLI 的实际拼接规则调整 `base_url`，确保最终 URL 命中已确认端点，避免重复 `/v1`。按服务协议与 CLI 能力选择实际支持的 `api_backend`，不硬套 `chat_completions`。用户要求实际测试时，只测试一个已选模型的简短请求，不自动轮测所有模型。
5. 无模型列表时依据用户提供的模型 ID 和服务信息继续判断，标记未验证；服务协议与当前 CLI 不兼容时报告具体限制和适配方案，不写入明知不可用的配置，也不只改 URL 就声称成功。

## 写入

1. 按前两节准备连接、识别端点及当前 CLI 的协议能力。
2. 使用已验证的模型列表；尚未获取时以规范连接请求 `GET {base_url}/models`。不重复已经成功的探测请求。
3. 每个新 id 追加一段。**id 含 `.` 时表名必须加引号。** 不加引号时 TOML 会把名字拆开，`/model` 里只剩半截，`grok inspect` 会出现 `unknown field`。

```toml
[model."example-model-1.5"]
model = "example-model-1.5"
base_url = "http://relay.example/v1"
name = "Example Model 1.5"
description = "第三方模型"
api_backend = "chat_completions"
context_window = 1000000
api_key = ""
```

上面示例是对话模型，`context_window` 用 `1000000`；图像模型用 `32000`。`api_key` 填 connection.json 中的实际密钥。示例中的 `api_backend` 仅适用于已确认使用 Chat Completions 的服务；实际值按当前 CLI 支持与服务协议填写。

4. 跑 `grok inspect`、`grok models`，核对配置解析和完整模型 ID。用户要求验证调用时，再通过当前 Grok CLI 做一次最小文本请求，核验最终端点与协议；未调用时标记推理未验证。Codex helper 成功不代表 Grok 客户端调用成功。
5. 报告规范地址、实际 `api_backend` 和验证结果；告诉用户当前会话的 `/model` 是启动时读的，新开一个 Grok 会话再选。
