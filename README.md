# PaperTrace - 论文参考文献智能搜索工具

<div align="center">

**智能拆分论文 · 精准搜索文献 · 自动生成引用**

[![Python](https://img.shields.io/badge/Python-3.x-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

</div>

---

## 项目概述

PaperTrace 是一个智能论文参考文献搜索工具，能够自动拆分论文内容并为每个片段搜索相关的参考文献。

**核心功能：**
- 使用阿里云百炼 API（通义千问）智能拆分论文为语义完整的片段
- 为每个片段独立分析，生成精准的搜索查询
- 使用 Tavily API 在学术网站上搜索每个片段可能引用的文献
- 自动生成符合 GB/T 7714-2015 标准的引用格式
- 支持三种成本控制模式，灵活管理 API 调用

**技术栈：**
- Python 3.x
- OpenAI SDK（用于调用阿里云百炼 API）
- Tavily Python SDK（用于网络搜索）
- python-dotenv（环境变量管理）

---

## 功能特性

### 三种搜索模式

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| 预算驱动 | 指定 API 调用上限，AI 自动规划最优方案 | 成本敏感场景 |
| 粒度控制 | 手动设置片段数、查询数等参数 | 精细控制需求 |
| 智能规划 | AI 生成经济/标准/深度三个方案供选择 | 不确定需求时 |

### 智能交互

- 支持任意步骤输入 `q` 退出程序
- 支持输入 `b` 返回上一步
- 完成一次搜索后可继续处理下一篇论文
- 输入错误时自动提示并重新输入

### 输出格式

- 完整保留原始论文内容
- 片段内容不截断，完整显示
- 参考文献摘要完整显示
- 自动生成引用格式（符合 GB/T 7714-2015）

---

## 项目结构

```
PaperTrace/
├── code/
│   └── paper_reference_searcher.py  # 主程序文件
├── docs/
│   └── API申请指南-中国用户版.md    # API Key 申请指南
├── ref/
│   └── 文后参考文献著录规则.doc     # 参考文献著录规则
├── .codefuse/
│   ├── CODEFUSE.md                  # 项目说明文档
│   ├── DESIGN.md                    # 设计思路文档
│   ├── pr/                          # 待处理需求
│   └── done/                        # 已完成需求
├── .env                              # 环境变量配置（需自行创建）
├── .envexample                       # 环境变量模板
├── .gitignore                        # Git 忽略配置
└── README.md                         # 项目说明
```

---

## 环境配置

### 1. 安装依赖

```bash
pip install openai tavily-python python-dotenv
```

### 2. 配置环境变量

复制 `.envexample` 为 `.env`，并填入 API Keys：

```bash
cp .envexample .env
```

编辑 `.env` 文件：

```env
# Tavily API Key（用于网络搜索）
TAVILY_API_KEY=tvly-your-api-key-here

# 阿里云百炼 API Key（用于论文分析）
BAILIAN_API_KEY=sk-your-api-key-here
```

### 3. 获取 API Keys

详细申请流程请参考 [API申请指南-中国用户版.md](docs/API申请指南-中国用户版.md)：

| API | 获取地址 | 免费额度 |
|-----|----------|----------|
| Tavily API | https://tavily.com/ | 每月 1,000 次免费调用 |
| 阿里云百炼 API | https://bailian.console.aliyun.com/ | 新用户有免费额度 |

---

## 运行方式

```bash
python code/paper_reference_searcher.py
```

程序会提示输入论文内容，然后自动拆分并搜索每个片段的相关文献。

---

## 使用指南

### 启动程序

运行程序后，首先输入论文内容：

```
请输入论文内容（输入空行结束）:
> 近年来，深度学习在自然语言处理领域取得了显著进展...
> 
```

### 选择搜索模式

程序提供三种模式：

```
请选择搜索模式:
1. 预算驱动模式（推荐）- 指定 API 调用上限
2. 粒度控制模式 - 手动设置参数
3. 智能规划模式 - AI 生成多个方案

请选择 (1-3):
```

#### 模式 1：预算驱动

```
请输入最大 API 调用次数 (5-100, 默认20): 15

预计拆分 4 个片段，每片段 2 个查询
预计 API 调用：13 次
  - 百炼 API：5 次（论文拆分 1 + 片段分析 4）
  - Tavily API：8 次（文献搜索，advanced 模式）
预计 Credits 消耗：21
  - 百炼 API：5 Credits
  - Tavily API：16 Credits（advanced 模式每次 2 Credits）

是否继续？(y/n):
```

#### 模式 2：粒度控制

```
请输入最大片段数 (1-20, 默认5): 5
请输入每片段查询数 (1-10, 默认2): 3
请输入每片段返回文献数 (1-10, 默认3): 3

预计 API 调用：15 次

是否继续？(y/n):
```

#### 模式 3：智能规划

```
AI 为您推荐以下方案：

1. 经济方案
   描述：快速检索核心文献，适合初步调研
   片段数：3，每片段查询数：2
   预计 API 调用：10 次
   预计 Credits 消耗：16（Tavily 每次 2 Credits）
   预计返回文献：9 篇

2. 标准方案
   描述：平衡覆盖度与成本，适合常规使用
   片段数：5，每片段查询数：3
   预计 API 调用：21 次
   预计 Credits 消耗：36
   预计返回文献：15 篇

3. 深度方案
   描述：全面检索相关文献，适合深入研究
   片段数：8，每片段查询数：4
   预计 API 调用：41 次
   预计 Credits 消耗：73
   预计返回文献：24 篇

请选择方案 (1-3):
```

### 交互操作

| 操作 | 命令 |
|------|------|
| 退出程序 | 输入 `q` 或 `quit` |
| 返回上一步 | 输入 `b` 或 `back` |
| 继续处理下一篇论文 | 完成后选择 `y` |

---

## 核心类说明

### `SearchMode`

搜索模式枚举：

| 值 | 说明 |
|------|------|
| `BUDGET` | 预算驱动模式 |
| `GRANULARITY` | 粒度控制模式 |
| `SMART` | 智能规划模式 |

### `SearchConfig`

统一的搜索配置类：

| 属性 | 说明 | 默认值 |
|------|------|--------|
| `mode` | 搜索模式 | `SearchMode.BUDGET` |
| `max_api_calls` | 最大 API 调用次数（预算模式） | 20 |
| `max_segments` | 最大片段数（粒度模式） | 5 |
| `queries_per_segment` | 每片段查询数（粒度模式） | 2 |
| `refs_per_segment` | 每片段返回文献数 | 3 |

### `ExecutionStats`

执行统计信息类：

| 属性 | 说明 |
|------|------|
| `segments_count` | 片段数量 |
| `total_queries` | 总查询数 |
| `bailian_calls` | 百炼 API 调用次数 |
| `tavily_calls` | Tavily API 调用次数 |
| `tavily_credits` | Tavily API Credits 消耗 |
| `total_credits` | 总 Credits 消耗 |

### `PaperSegment`

论文片段数据结构：

| 属性 | 说明 |
|------|------|
| `segment_id` | 片段序号 |
| `title` | 片段标题 |
| `content` | 片段内容 |
| `segment_type` | 片段类型（background/method/experiment/discussion/conclusion/other） |
| `key_concepts` | 关键概念列表 |
| `priority` | 优先级（method=3, experiment=2, background=1） |
| `search_queries` | 生成的搜索查询 |
| `references` | 找到的参考文献列表 |

### `PaperReferenceSearcher`

主类，提供以下方法：

| 方法 | 说明 |
|------|------|
| `analyze_complexity(paper_content)` | 分析论文复杂度，返回推荐片段数 |
| `plan_with_budget(paper_content)` | 根据预算规划拆分方案 |
| `generate_plan_options(paper_content)` | 生成多个方案供用户选择 |
| `split_paper(paper_content)` | 智能拆分论文为语义片段 |
| `analyze_segment(segment)` | 分析单个片段，生成搜索查询 |
| `search_references_for_segment(segment, queries)` | 为片段搜索参考文献 |
| `search_paper_references(paper_content)` | 完整的搜索流程 |
| `format_results(results)` | 格式化输出结果（文本格式） |
| `format_markdown_results(results)` | 格式化输出结果（Markdown 格式） |

---

## 处理流程

```
论文输入 → 智能拆分 → 片段分析 → 文献搜索 → 结果整合
```

1. **智能拆分**：按语义单元拆分论文（背景、方法、实验、讨论等）
2. **片段分析**：为每个片段生成精准搜索查询
3. **文献搜索**：在学术网站搜索相关文献
4. **结果整合**：按片段组织输出，生成引用格式

---

## 搜索范围

Tavily 搜索限定在以下学术网站：

| 网站 | 说明 |
|------|------|
| arxiv.org | 预印本论文库 |
| scholar.google.com | Google 学术搜索 |
| dl.acm.org | ACM 数字图书馆 |
| ieeexplore.ieee.org | IEEE Xplore |
| springer.com | Springer 出版社 |
| nature.com | Nature 期刊 |
| science.org | Science 期刊 |
| semanticscholar.org | Semantic Scholar |
| pubmed.ncbi.nlm.nih.gov | PubMed 医学文献库 |

---

## API 成本说明

### 百炼 API

- 模型：qwen-plus
- 费用：约 0.004 元/千 tokens
- 分析一篇论文通常花费不到 0.1 元

### Tavily API

- 模式：advanced（每次消耗 2 Credits）
- 免费额度：每月 1,000 Credits
- 预估：可搜索约 500 次

### Credits 计算公式

```
总 Credits = 百炼调用次数 + Tavily调用次数 × 2

其中：
- 百炼调用 = 1（论文拆分）+ segments（片段分析）
- Tavily调用 = segments × queries_per_segment
```

---

## 开发说明

- 默认使用 `qwen-plus` 模型进行论文分析
- 片段按优先级排序（method > experiment > background）
- 搜索结果自动去重并按相关性排序
- 支持文本和 Markdown 两种输出格式
- 引用格式符合 GB/T 7714-2015 标准

---

## 详细设计

请参考 [DESIGN.md](docs/DESIGN.md) 了解详细的设计思路和架构说明。

---

## 许可证

本项目采用 MIT 许可证。