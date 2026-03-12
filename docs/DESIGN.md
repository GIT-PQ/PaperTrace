# PaperTrace 系统设计文档

## 一、系统概述

PaperTrace 是一个智能论文参考文献搜索工具，通过 AI 技术自动拆分论文内容并为每个片段搜索相关的参考文献。

### 核心能力

- **智能拆分**：使用 LLM 将论文按语义单元拆分为独立片段
- **精准搜索**：为每个片段生成针对性搜索查询，在学术网站检索
- **成本控制**：支持三种模式灵活管理 API 调用成本
- **引用生成**：自动生成符合 GB/T 7714-2015 标准的引用格式

---

## 二、系统架构

### 整体架构图

```mermaid
graph TB
    subgraph 用户交互层
        A[用户输入论文] --> B[模式选择]
        B --> C1[预算驱动模式]
        B --> C2[粒度控制模式]
        B --> C3[智能规划模式]
    end
    
    subgraph 核心处理层
        D[论文拆分器]
        E[片段分析器]
        F[文献搜索器]
        G[结果整合器]
    end
    
    subgraph API 服务层
        H[阿里云百炼 API]
        I[Tavily API]
    end
    
    subgraph 输出层
        J[文本格式输出]
        K[Markdown 格式输出]
    end
    
    C1 --> D
    C2 --> D
    C3 --> D
    D --> H
    D --> E
    E --> H
    E --> F
    F --> I
    F --> G
    G --> J
    G --> K
```

---

## 三、完整处理流程

### 主流程图

```mermaid
flowchart TD
    Start([开始]) --> Input[/输入论文内容/]
    Input --> ModeSelect{选择搜索模式}
    
    %% 预算驱动模式
    ModeSelect -->|1. 预算驱动| BudgetInput[/输入最大 API 调用次数/]
    BudgetInput --> BudgetPlan[AI 规划拆分方案]
    BudgetPlan --> BudgetConfirm{确认执行?}
    BudgetConfirm -->|是| SplitPaper
    BudgetConfirm -->|否| ModeSelect
    
    %% 粒度控制模式
    ModeSelect -->|2. 粒度控制| GranInput[/输入参数: 片段数/查询数/文献数/]
    GranInput --> GranConfirm{确认执行?}
    GranConfirm -->|是| SplitPaper
    GranConfirm -->|否| ModeSelect
    
    %% 智能规划模式
    ModeSelect -->|3. 智能规划| SmartPlan[AI 生成三个方案]
    SmartPlan --> SmartSelect[/选择方案/]
    SmartSelect --> SmartConfirm{确认执行?}
    SmartConfirm -->|是| SplitPaper
    SmartConfirm -->|否| ModeSelect
    
    %% 核心处理流程
    SplitPaper[步骤1: 智能拆分论文]
    SplitPaper --> |百炼 API| SplitResult[获取片段列表]
    SplitResult --> SetPriority[设置片段优先级]
    SetPriority --> SortSegments[按优先级排序]
    
    SortSegments --> AnalyzeLoop{遍历每个片段}
    AnalyzeLoop --> |百炼 API| AnalyzeSegment[步骤2: 分析片段生成查询]
    AnalyzeSegment --> StoreQueries[存储搜索查询]
    StoreQueries --> AnalyzeLoop
    
    AnalyzeLoop -->|完成| SearchLoop{遍历每个片段}
    SearchLoop --> |Tavily API| SearchRefs[步骤3: 搜索参考文献]
    SearchRefs --> DedupResults[URL 去重]
    DedupResults --> StoreRefs[存储参考文献]
    StoreRefs --> SearchLoop
    
    SearchLoop -->|完成| Integrate[步骤4: 整合结果]
    Integrate --> GenCitation[生成引用格式]
    GenCitation --> Output[输出结果]
    
    Output --> Continue{继续处理?}
    Continue -->|是| Input
    Continue -->|否| End([结束])
```

### 详细处理流程

```mermaid
sequenceDiagram
    participant U as 用户
    participant M as 主程序
    participant B as 百炼 API
    participant T as Tavily API
    
    U->>M: 输入论文内容
    M->>M: 选择搜索模式
    
    rect rgb(240, 248, 255)
        Note over M,B: 步骤1: 论文拆分
        M->>B: 发送论文内容
        B-->>M: 返回片段列表
        M->>M: 设置优先级并排序
    end
    
    rect rgb(255, 250, 240)
        Note over M,B: 步骤2: 片段分析
        loop 每个片段
            M->>B: 发送片段内容
            B-->>M: 返回搜索查询
        end
    end
    
    rect rgb(240, 255, 240)
        Note over M,T: 步骤3: 文献搜索
        loop 每个片段
            loop 每个查询
                M->>T: 发送搜索请求
                T-->>M: 返回搜索结果
            end
            M->>M: 去重并排序
        end
    end
    
    rect rgb(255, 240, 245)
        Note over M: 步骤4: 结果整合
        M->>M: 生成引用格式
        M->>M: 统计 API 调用
    end
    
    M-->>U: 输出完整结果
```

---

## 四、核心类设计

### 类图

```mermaid
classDiagram
    class SearchMode {
        <<enumeration>>
        BUDGET
        GRANULARITY
        SMART
    }
    
    class SearchConfig {
        +SearchMode mode
        +int max_api_calls
        +int max_segments
        +int queries_per_segment
        +int refs_per_segment
        +estimate_api_calls() int
    }
    
    class ExecutionStats {
        +int segments_count
        +int total_queries
        +int bailian_calls
        +int tavily_calls
        +int tavily_credits
        +int failed_calls
        +int total_refs
        +int unique_refs
        +api_calls() int
        +total_credits() int
        +to_string() str
    }
    
    class PaperSegment {
        +int segment_id
        +str title
        +str content
        +str segment_type
        +List key_concepts
        +int priority
        +List search_queries
        +List references
        +to_dict() Dict
    }
    
    class PaperReferenceSearcher {
        -SEGMENT_PRIORITY: Dict
        +SearchConfig config
        +ExecutionStats stats
        +analyze_complexity(paper_content) int
        +plan_with_budget(paper_content) Dict
        +generate_plan_options(paper_content) List
        +split_paper(paper_content) List~PaperSegment~
        +analyze_segment(segment) List~str~
        +search_references_for_segment(segment, queries) List~Dict~
        +search_paper_references(paper_content) Dict
        +format_results(results) str
        +format_markdown_results(results) str
        -_generate_citation(ref, index) str
    }
    
    SearchConfig --> SearchMode
    PaperReferenceSearcher --> SearchConfig
    PaperReferenceSearcher --> ExecutionStats
    PaperReferenceSearcher --> PaperSegment
```

### 核心类说明

#### SearchConfig

统一的搜索配置类，管理搜索参数：

| 属性 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `mode` | SearchMode | 搜索模式 | BUDGET |
| `max_api_calls` | int | 最大 API 调用次数 | 20 |
| `max_segments` | int | 最大片段数 | 5 |
| `queries_per_segment` | int | 每片段查询数 | 2 |
| `refs_per_segment` | int | 每片段文献数 | 3 |

#### ExecutionStats

执行统计信息类，记录运行数据：

| 属性 | 说明 |
|------|------|
| `bailian_calls` | 百炼 API 调用次数 |
| `tavily_calls` | Tavily API 调用次数 |
| `tavily_credits` | Tavily Credits 消耗（advanced 模式每次 2 Credits） |
| `total_credits` | 总 Credits 消耗 |

#### PaperSegment

论文片段数据结构：

| 属性 | 说明 |
|------|------|
| `segment_type` | 片段类型（background/method/experiment/discussion/conclusion/other） |
| `priority` | 优先级（method=3, experiment=2, background=1） |
| `key_concepts` | 关键概念列表 |
| `search_queries` | 生成的搜索查询 |
| `references` | 找到的参考文献列表 |

---

## 五、三种搜索模式

### 模式对比

```mermaid
graph LR
    subgraph 预算驱动模式
        A1[用户指定 API 上限] --> B1[AI 自动规划]
        B1 --> C1[最优方案]
    end
    
    subgraph 粒度控制模式
        A2[用户指定参数] --> B2[精确控制]
        B2 --> C2[自定义方案]
    end
    
    subgraph 智能规划模式
        A3[AI 分析论文] --> B3[生成三个方案]
        B3 --> C3[用户选择]
    end
```

### 预算驱动模式

用户指定 API 调用上限，AI 自动规划最优拆分方案：

```python
# 预估公式
estimated_credits = 1 + segments + segments * queries_per_segment * 2

# 其中：
# 1 = 论文拆分（百炼）
# segments = 片段分析（百炼）
# segments * queries * 2 = 文献搜索（Tavily advanced 模式）
```

### 粒度控制模式

用户手动设置所有参数：
- 最大片段数（1-20）
- 每片段查询数（1-10）
- 每片段返回文献数（1-10）

### 智能规划模式

AI 分析论文复杂度后生成三个方案：

| 方案 | 片段数 | 查询数/片段 | 预估 Credits | 适用场景 |
|------|--------|-------------|--------------|----------|
| 经济 | 3 | 2 | 16 | 初步调研 |
| 标准 | 5 | 3 | 36 | 常规使用 |
| 深度 | 8 | 4 | 73 | 深入研究 |

---

## 六、API 调用统计

### 调用流程

```mermaid
flowchart LR
    subgraph 百炼 API
        A[论文拆分<br/>1 次] --> B[片段分析<br/>N 次]
    end
    
    subgraph Tavily API
        C[文献搜索<br/>N × Q 次]
    end
    
    B --> C
    
    Note1[总调用 = 1 + N + N×Q<br/>总 Credits = 1 + N + N×Q×2]
```

### Credits 计算示例

假设：segments=5, queries_per_segment=3

| API 类型 | 调用次数 | Credits |
|----------|----------|---------|
| 百炼（拆分） | 1 | 1 |
| 百炼（分析） | 5 | 5 |
| Tavily（搜索） | 15 | 30 |
| **总计** | **21** | **36** |

---

## 七、交互设计

### 用户交互流程

```mermaid
stateDiagram-v2
    [*] --> 输入论文
    输入论文 --> 选择模式
    
    选择模式 --> 预算驱动: 1
    选择模式 --> 粒度控制: 2
    选择模式 --> 智能规划: 3
    
    预算驱动 --> 输入预算
    输入预算 --> 确认执行
    确认执行 --> 执行搜索: y
    确认执行 --> 选择模式: n 或 back
    输入预算 --> 选择模式: back
    
    粒度控制 --> 输入参数
    输入参数 --> 确认执行2
    确认执行2 --> 执行搜索: y
    确认执行2 --> 选择模式: n 或 back
    输入参数 --> 选择模式: back
    
    智能规划 --> 显示方案
    显示方案 --> 选择方案
    选择方案 --> 确认执行3
    确认执行3 --> 执行搜索: y
    确认执行3 --> 显示方案: n 或 back
    选择方案 --> 显示方案: back
    
    执行搜索 --> 显示结果
    显示结果 --> 继续处理?
    继续处理? --> 输入论文: y
    继续处理? --> [*]: n 或 quit
    
    note right of 选择模式
        输入 q/quit 退出
        输入 b/back 返回
    end note
```

### 交互命令

| 命令 | 说明 |
|------|------|
| `q` / `quit` | 退出程序 |
| `b` / `back` | 返回上一步 |
| `y` / `n` | 确认/取消 |

---

## 八、输出格式

### 文本格式

```
======================================================================
论文参考文献搜索结果
======================================================================

----------------------------------------------------------------------
原始论文内容
----------------------------------------------------------------------
[完整论文内容]

----------------------------------------------------------------------
搜索结果摘要
----------------------------------------------------------------------
共拆分为 5 个片段
共找到 25 篇参考文献
去重后 18 篇
每个片段最多 3 篇参考文献
API 调用：21 次
  - 百炼 API：6 次
  - Tavily API：15 次（advanced 模式）
Credits 消耗：36
  - 百炼 API：6 Credits
  - Tavily API：30 Credits（每次 2 Credits）

----------------------------------------------------------------------
## 片段 1: 方法描述
----------------------------------------------------------------------
类型: method
关键概念: Transformer, Attention, Self-attention

片段内容:
[完整片段内容]

搜索查询:
  1. transformer attention mechanism original paper
  2. self-attention neural network

推荐参考文献 (3 篇):

  [1] Attention Is All You Need
      URL: https://arxiv.org/abs/1706.03762
      相关性: 0.95
      来源查询: transformer attention mechanism original paper
      引用格式: [1] Attention Is All You Need[EB/OL]. arXiv预印本, 2026-03-12. https://arxiv.org/abs/1706.03762
      摘要: [完整摘要]
```

### 引用格式

符合 GB/T 7714-2015 标准：

```
[序号] 标题[EB/OL]. 来源, 访问日期. URL
```

示例：
```
[1] Attention Is All You Need[EB/OL]. arXiv预印本, 2026-03-12. https://arxiv.org/abs/1706.03762
```

---

## 九、降级处理

为保证系统稳定性，设计了以下降级策略：

```mermaid
flowchart TD
    A[API 调用] --> B{调用成功?}
    B -->|是| C[正常处理]
    B -->|否| D{哪个 API?}
    
    D -->|拆分失败| E[降级: 整篇论文作为单一片段]
    D -->|分析失败| F[降级: 使用关键概念生成查询]
    D -->|搜索失败| G[降级: 跳过该查询继续其他]
    
    E --> H[继续流程]
    F --> H
    G --> I[记录失败次数]
    I --> H
```

| 失败场景 | 降级策略 |
|----------|----------|
| 论文拆分失败 | 将整个论文作为单一片段处理 |
| 片段分析失败 | 使用片段的关键概念生成简单查询 |
| 文献搜索失败 | 跳过该查询，继续其他查询 |

---

## 十、技术选型

| 组件 | 技术方案 | 原因 |
|------|---------|------|
| 论文分析 | 阿里云百炼（通义千问） | 中文理解能力强，API 稳定，成本低 |
| 文献搜索 | Tavily API | 专为 AI Agent 设计，支持学术域名限定 |
| 环境管理 | python-dotenv | 安全管理 API Key |
| 数据结构 | dataclass | 简洁的数据类定义 |

### 学术搜索域名

| 域名 | 说明 |
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

## 十一、未来优化方向

1. **缓存机制**：对相似查询结果进行缓存，减少 API 调用
2. **并行处理**：多片段并行搜索，提升效率
3. **相关性优化**：结合片段语义和搜索结果进行二次排序
4. **更多引用格式**：支持 APA、MLA 等多种引用格式
5. **本地模型支持**：支持本地部署的 LLM，降低 API 依赖