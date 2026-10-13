# 第三方模型调度示例

用于演练 Codex 版 `mod-dispatch` 的小型示例项目。`config_demo.py` 最初带有缺陷，当前版本由第三方模型提出补丁、Codex 应用并通过验收测试。

## 任务

修复 `load_settings(env)`，只修改 `config_demo.py`，保留函数名和返回字段：

- `APP_DEBUG` 缺省为 `False`。忽略首尾空白和大小写，`true/1/yes/on` 对应 `True`，`false/0/no/off` 对应 `False`，其他值（包括空字符串）抛出 `ValueError`。
- `APP_TIMEOUT` 缺省为 `30`。采用 Python `int()` 的十进制字符串转换规则，结果必须大于零；允许 `+5`、` 5 ` 和 `05`，非整数、空字符串、零或负数抛出 `ValueError`。
- `debug` 必须为 `bool`，`timeout_seconds` 必须为 `int`，不能修改传入的字典。
- 不修改测试来迎合错误行为，不引入依赖，不读取真实系统环境变量。

## 验收

在 `mod-agent-skills` 根目录运行，不生成字节码缓存：

```sh
python3 -B -m unittest discover -s example -v
```

## 连接与调度

连接文件由 `mod-add` 生成在技能包根目录 `../connection.json`（相对于本示例目录），填写 `base_url` 和 `api_key` 后即可调度。模型 ID 按中转站实际提供的值配置。

实测顺序为：`models` 核对连接和角色 → `read` 分析示例 → `brain` 确定修复方案 → `write` 生成补丁 → Codex 应用并运行测试 → `review` 审核实际修改与测试结果。

## 本次实测结果（2026-10-13）

- 实际请求确认入口的 `/models` 返回 404，`/v1/models` 成功，因此将连接文件中的基础地址规范为带 `/v1` 的路径。返回的 38 个模型 ID 包含全部四个配置角色。
- `read`（`deepseek-flash`）、`brain`（`gpt-6-luna`）、`write`（`deepseek-v4-pro`）和 `review`（`grok-4.7`）均通过真实 Chat Completions 请求返回完整结果。
- 补丁应用前核对文件 SHA-256，只修改 `config_demo.py`。验收从 7 个测试方法中的 12 个失败项变为全部通过；Grok 审查通过，测试文件未修改。
- 本次验证的是 Codex 的外部模型调度链。Grok CLI 原生客户端的 URL 拼接与调用需按 Grok 版 `mod-add` 单独验证，不能用上述结果代替。
