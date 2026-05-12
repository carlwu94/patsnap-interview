# 锂离子电池专利问答平台

本项目实现了一个本地运行的专利查询 Web 应用，覆盖数据入库、全文检索、IPC 统计、MCP Tools 和 chatbot 式 Agent 交互。后端基于 FastAPI + SQLite FTS5，MCP 侧使用 FastMCP，Web 页面以聊天为主入口，同时展示结构化检索结果与工具调用轨迹。聊天 Agent 使用 OpenAI 兼容 tool-calling 生成工具调用决策，并通过 FastMCP Client 接入本地 MCP Server 执行查询工具。

## 1. 环境准备

### 操作系统

- Windows 10 / 11
- 下面的命令示例默认使用 PowerShell

### Python 版本

- Python 3.14
- 当前仓库已使用 `.venv`

### 必需依赖库

仓库已经提供 [requirements.txt](requirements.txt)。主要依赖包括：

- `fastapi`
- `uvicorn[standard]`
- `jinja2`
- `httpx`
- `openai`
- `fastmcp`
- `pymupdf`
- `pandas`
- `openpyxl`
- `pydantic`
- `rapidocr_onnxruntime`
- `pytest`

### 从零安装依赖

如果你还没有虚拟环境，可以从零执行：

```powershell
cd e:/workspace/patsnap-interview
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

如果你直接使用当前仓库已有虚拟环境，可以执行：

```powershell
e:/workspace/patsnap-interview/.venv/Scripts/python.exe -m pip install -r requirements.txt
```

### Agent / LLM 配置

默认配置模板在根目录的 `appsettings.example.toml`。你可以复制为 `appsettings.toml` 后按需填写，并在其中配置：

- DeepSeek API Key
- DeepSeek Base URL
- DeepSeek 模型名
- 是否启用 OCR fallback
- 导入时的提交频率和进度打印频率

示例：

```toml
[llm]
api_key = "<your-api-key>"
base_url = "https://api.deepseek.com/v1"
model = "deepseek-v4-pro"

[ingestion]
use_ocr_fallback = true
commit_interval = 20
progress_interval = 20
```

也支持环境变量覆盖：

```powershell
$env:DEEPSEEK_API_KEY = "<your-api-key>"
$env:DEEPSEEK_MODEL = "deepseek-v4-pro"
$env:DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
```

当前已验证可用模型名包括：

- `deepseek-v4-pro`
- `deepseek-v4-flash`

如果未配置模型，聊天接口会自动退回规则兜底模式，仍可完成本地演示。

## 2. 数据准备说明

### 题目要求下的推荐目录结构

如果你需要自己放置 500 篇 PDF 和 Excel 元数据文件，建议采用以下路径结构：

```text
target/
  笔试数据包/
    20260510125342232/
      index.xlsx
      pdf/
        CNXXXXXXXA.pdf
        CNXXXXXXXB.pdf
        ... 共 500 篇 PDF
```

### 代码默认读取的位置

当前代码默认读取：

- Excel 元数据：`target/笔试数据包/20260510125342232/index.xlsx`
- PDF 目录：`target/笔试数据包/20260510125342232/pdf/`

### 当前仓库内的实际数据位置

本仓库已经包含题目数据，实际路径也是：

- 元数据：`target/笔试数据包/20260510125342232/index.xlsx`
- PDF：`target/笔试数据包/20260510125342232/pdf/`

### 额外说明

- 题目文字里常见写法是 `patent_metadata.xlsx`，但本仓库实际文件名是 `index.xlsx`
- 当前实现已经按中文表头完成字段映射，无需再手工改 Excel 列名
- PDF 文件名由专利公开号映射，例如 `CN103682295A.pdf`

## 3. 目录结构

```text
app/
  agent/          # Agent 聊天逻辑与 OpenAI 兼容模型适配
  db/             # SQLite 连接、建表、Excel + PDF 入库
  mcp/            # FastMCP server
  services/       # 核心查询函数
  web/            # FastAPI 路由与页面
scripts/
  init_db.py
  run_web.py
  run_mcp_server.py
  demo_client.py
  demo_mcp_client.py
static/
templates/
tests/
requirements.txt
README.md
```

## 4. 从零开始运行的完整步骤

下面这组命令从依赖安装到 Web 演示是完整闭环。

### 4.1 安装依赖

```powershell
cd e:/workspace/patsnap-interview
e:/workspace/patsnap-interview/.venv/Scripts/python.exe -m pip install -r requirements.txt
```

### 4.2 初始化数据库并导入 500 篇专利

先做小样本验证：

```powershell
e:/workspace/patsnap-interview/.venv/Scripts/python.exe scripts/init_db.py --limit 100
```

全量导入：

```powershell
e:/workspace/patsnap-interview/.venv/Scripts/python.exe scripts/init_db.py
```

导入完成后会生成：

- `artifacts/patents.sqlite3`：SQLite 数据库
- `logs/parse_activity.csv`：每篇专利的处理进度日志
- `logs/parse_failures.csv`：仅记录失败样本

### 4.3 启动 Web 应用

```powershell
e:/workspace/patsnap-interview/.venv/Scripts/python.exe scripts/run_web.py
```

浏览器访问：

```text
http://127.0.0.1:9876
```

### 4.4 启动 MCP Server

```powershell
e:/workspace/patsnap-interview/.venv/Scripts/python.exe scripts/run_mcp_server.py
```

说明：

- 当前 MCP Server 以 stdio 模式运行
- 适合被本仓库内置 FastMCP Client 接入

## 5. 如何测试 MCP Tools

## 可用 MCP Tools

当前共暴露 5 个工具：

- `list_assignees`
- `search_patents`
- `get_patent_details`
- `get_top_ipc`
- `get_assignee_trend`

### 5.1 启动 MCP Server

```powershell
e:/workspace/patsnap-interview/.venv/Scripts/python.exe scripts/run_mcp_server.py
```

### 5.2 使用内置 Client 脚本验证全部 Tool

仓库内置了一个简单 Client 脚本，会自动：

- 列出全部可用工具
- 调用 `list_assignees`
- 调用 `search_patents`
- 调用 `get_patent_details`
- 调用 `get_assignee_trend`
- 调用 `get_top_ipc`

执行命令：

```powershell
e:/workspace/patsnap-interview/.venv/Scripts/python.exe scripts/demo_mcp_client.py
```

如果脚本正常打印出 5 个工具的返回结果，就说明 MCP Server 与 5 个 Tool 都工作正常。

### 5.3 预期输出示例

输出中你会看到类似：

```text
Tools:
[
  "list_assignees",
  "search_patents",
  "get_patent_details",
  "get_top_ipc",
  "get_assignee_trend"
]
```

然后依次打印每个 Tool 的 JSON 结果。

## 6. 如何运行 Agent

本项目不是 Dify 工作流，也没有单独的命令行 Agent；当前 Agent 的运行方式是 Web Agent，通过 FastAPI 页面和 `/api/chat` / `/api/chat/stream` 接口提供服务。

### 6.1 启动 Agent

启动命令就是启动 Web 应用：

```powershell
e:/workspace/patsnap-interview/.venv/Scripts/python.exe scripts/run_web.py
```

打开浏览器：

```text
http://127.0.0.1:9876
```

页面左侧 Chatbot 区域就是 Agent 入口。

### 6.2 Agent 示例对话

你可以直接在聊天框输入：

- `帮我检索所有提到“固态电解质”的专利`
- `列出宁德时代在 2024 年期间申请的专利`
- `这 500 篇专利中，最热门的 5 个 IPC 分类号是什么？`
- `先搜一下锂离子电池正极相关的专利，然后查看第一篇的详细内容`
- `列出数据库里的所有公司名称`

### 6.3 使用 HTTP 接口验证 Agent

如果你想不打开浏览器，直接测试 Agent，可在 Web 服务启动后执行：

```powershell
$body = @{
  message = "列出宁德时代在 2024 年期间申请的专利"
  model = "deepseek-v4-pro"
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://127.0.0.1:9876/api/chat" -Method Post -ContentType "application/json" -Body $body
```

### 6.4 Web / HTTP 调用验证脚本

也可以直接运行仓库内置的 HTTP Demo：

```powershell
e:/workspace/patsnap-interview/.venv/Scripts/python.exe scripts/demo_client.py
```

该脚本会调用：

- `/api/health`
- `/api/search`
- `/api/chat`

## 7. 测试

运行最小自动化测试：

```powershell
e:/workspace/patsnap-interview/.venv/Scripts/python.exe -m pytest tests -q
```

## 8. 常见问题

### 8.1 PDF 解析失败

失败样本会被记录到 `logs/parse_failures.csv`。当前版本会先尝试直接提取 PDF 文本层；如果页面没有文本层，会自动对图片型页面执行 OCR fallback。仍然失败的样本会被标记为 `extract_failed` 或 `empty_text`。

如果你想临时关闭 OCR fallback，可以把 `appsettings.toml` 里的 `use_ocr_fallback` 改成 `false`。

### 8.2 数据库连接或数据库被占用

如果你在导入时反复启动多个脚本，SQLite 可能被其他进程占用。常见处理方式：

- 关闭所有旧的 `init_db.py` / Web / 测试进程
- 删除或备份旧的 `artifacts/patents.sqlite3`
- 重新执行 `scripts/init_db.py`

### 8.3 聊天回答没有走大模型

如果页面显示“未配置模型，当前走规则兜底”，说明没有设置 `DEEPSEEK_API_KEY` 和 `DEEPSEEK_MODEL`，或者没有设置通用的 `LLM_API_KEY` 和 `LLM_MODEL`。这不影响本地演示，但回答会更偏规则化。

### 8.4 PowerShell 报 profile 执行策略警告

这是本机 PowerShell 配置导致的警告，不影响 Python 脚本运行。
