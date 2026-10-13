# Mod agent skills

一套简单的模型调度技能。主会话只负责派活，通读、拍板、改文件、审核交给不同角色。它不包含任何一个 Minecraft 模组的设计、代码或进度。

这套技能起初是给一位模组开发者定做的简单版本：活按文件切开，读的人和改的人不写同一个文件，方案没定下来就不改代码，改完一项就审一项。角色和模型都可以换。以 MIT 许可发布，允许二次修改、再分发和嵌进自己的流程。

Grok 里一次只读审批长这样。`deepseek-flash` 按文件通读，`grok-4.7` 按文件审核，审核过程不改文件。

![Grok 调度审批](docs/grok-dispatch.png)

## 两套客户端

| 客户端 | 配置 | 调度 | 调用 |
|---|---|---|---|
| Grok CLI | `mod-add/` | `mod-dispatch/` | `/mod-add`、`/mod-dispatch`，原生子代理 |
| Codex | `codex/mod-add/` | `codex/mod-dispatch/` | `$mod-add`、`$mod-dispatch`，`relay.py` 调 Chat Completions |

不要把两套同名目录装进同一个 skills 目录。Grok 用 `/`，这是 Grok 自己的命令。Codex 用 `$`。

默认角色只是起点，中转站不一定有这些 ID。配置时以服务返回的模型列表为准。

| 角色 | 默认模型 | 做什么 |
|---|---|---|
| `read` | `deepseek-flash` | 通读，带回路径和行号 |
| `write` | `deepseek-v4-pro` | 按已定方案改文件 |
| `brain` | `gpt-6-luna` | 架构、根因和取舍 |
| `review` | `grok-4.7` | 一项改完立刻审 |

## 安装 Grok

把 `mod-add` 和 `mod-dispatch` 放到 `~/.grok/skills/`。复制一份即可：

```sh
mkdir -p ~/.grok/skills
cp -R mod-add mod-dispatch ~/.grok/skills/
```

如果这个仓库就是你要改的源码，用符号链接，改完即对 Grok 生效：

```sh
ln -s "$PWD/mod-add" ~/.grok/skills/mod-add
ln -s "$PWD/mod-dispatch" ~/.grok/skills/mod-dispatch
```

新开一个 Grok 会话后，斜杠菜单里会出现 `/mod-add` 和 `/mod-dispatch`。

`/mod-add` 第一次会问要不要把中转站上还没进 `/model` 的对话模型和图像模型加进去。视频模型默认不加，需要时加上 `--video`。选择写在 `~/.grok/skills/mod-add/state.json`，这个文件不提交。

模型写进 `~/.grok/config.toml`。id 里有 `.` 时表名要加引号，例如 `[model."example-model-1.5"]`。对话模型的 `context_window` 用 `1000000`，图像模型用 `32000`。`api_key` 填连接文件里的密钥，不要把说明文字写进配置。当前会话的 `/model` 是启动时读的，加完要新开一个会话再选。不要改 `[models].default`。

## 安装 Codex

需要 macOS 或 Linux、Python 3.9+，以及能访问中转站的网络。没有第三方 Python 依赖。Codex 负责组织上下文、应用补丁和跑验证。第三方模型只看到这次给出的任务和文件快照，不跑 shell，也不改项目。

```sh
mkdir -p ~/.agents/skills
cp -R codex/mod-add codex/mod-dispatch ~/.agents/skills/
```

也可以装到项目里的 `.agents/skills/`。装好后输入 `$mod-add` 或 `$mod-dispatch`，没出现就重启 Codex。

也可以直接调脚本。任务走标准输入，结果走标准输出：

```sh
RELAY="$HOME/.agents/skills/mod-dispatch/scripts/relay.py"
python3 -B "$RELAY" init
python3 -B "$RELAY" models
printf '%s' '分析配置加载路径，引用具体文件与行号。' |
  python3 -B "$RELAY" ask --role read --workspace /absolute/project \
    --file src/config.py
```

`--config` 要放在子命令前面。`ask` 和 `models` 可以用 `--timeout`，默认 120 秒。附件只接受项目内的 UTF-8 文件，任务和附件合计不超过 1 MiB。

从仓库根目录跑测试。测试用内存里的文件和 HTTP 替身，不访问真实中转站：

```sh
python3 -B -m unittest discover -s codex/tests -v
```

`example/` 是一个很小的配置加载示例，用来走一遍 Codex 调度。没有连接信息时只做本地测试，不要把本地通过说成模型已经调通。

## 连接文件

真实地址和密钥放在本地的 `connection.json`，权限 `0600`。这个文件已经写进 `.gitignore`，不要提交，也不要填进 `connection.example.json`。

示例只说明形状：

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

直接使用本仓库时，两套技能共用仓库根目录的 `connection.json`。复制安装之后：

- Grok：`~/.grok/skills/connection.json`
- Codex 用户目录：`~/.agents/skills/connection.json`
- Codex 项目目录：`.agents/skills/connection.json`

没有连接信息时，技能会生成空文件并让你补。地址可以是域名、API 基础路径或完整端点。代理会核对少量同主机候选，确认后再保存规范地址。401、403、429 按认证、权限或限流处理，不把密钥发到另一台主机。

代码和任务内容会发到你配置的中转站，并消耗那里的额度。

## 二次修改

改角色分工时，Grok 看 `mod-dispatch/SKILL.md` 里的表，Codex 看连接文件的 `models` 和 `codex/mod-dispatch/SKILL.md`。改一处就让另一处指向它，不要把同一条规则抄成两份然后各改各的。

可以换模型 ID、收紧审核轮数，或改成你自己的构建和测试命令。项目自己的包名、构建命令和设计文档以那个项目为准，不要写死在技能里。

## 许可

MIT，见 [LICENSE](LICENSE)。
