"""
论文参考文献搜索工具
使用阿里云百炼API智能拆分论文并搜索每个片段可能引用的文献
"""

import os
import json
from typing import List, Dict, Optional
from dataclasses import dataclass, field
from enum import Enum
from openai import OpenAI
from tavily import TavilyClient
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()


class SearchMode(Enum):
    """搜索模式枚举"""
    BUDGET = "budget"           # 预算驱动模式
    GRANULARITY = "granularity" # 粒度控制模式
    SMART = "smart"             # 智能规划模式


@dataclass
class SearchConfig:
    """统一的搜索配置"""
    mode: SearchMode = SearchMode.BUDGET
    
    # 预算模式参数
    max_api_calls: int = 20
    
    # 粒度模式参数
    max_segments: int = 5
    queries_per_segment: int = 2
    
    # 通用参数
    refs_per_segment: int = 3
    
    def estimate_api_calls(self) -> int:
        """预估 API 调用次数"""
        if self.mode == SearchMode.BUDGET:
            return self.max_api_calls
        elif self.mode == SearchMode.GRANULARITY:
            return self.max_segments * self.queries_per_segment
        else:
            return 0  # 智能模式需要先分析


@dataclass
class ExecutionStats:
    """执行统计信息"""
    segments_count: int = 0
    total_queries: int = 0
    api_calls: int = 0
    failed_calls: int = 0
    total_refs: int = 0
    unique_refs: int = 0
    
    def to_string(self, monthly_limit: int = 1000) -> str:
        """格式化统计信息"""
        lines = [
            "========== 执行统计 ==========",
            f"片段数量：{self.segments_count}",
            f"总查询数：{self.total_queries}",
            f"API 调用：{self.api_calls} 次",
        ]
        if self.failed_calls > 0:
            lines.append(f"  （{self.failed_calls} 个查询无结果）")
        lines.append(f"返回文献：{self.total_refs} 篇（去重后 {self.unique_refs} 篇）")
        if self.api_calls > 0:
            percentage = (self.api_calls / monthly_limit) * 100
            lines.append(f"预估成本：{self.api_calls}/{monthly_limit} ({percentage:.1f}%)")
        lines.append("==============================")
        return "\n".join(lines)

# 阿里云百炼配置
BAILIAN_API_KEY = os.environ.get("BAILIAN_API_KEY")
BAILIAN_BASE_URL = os.environ.get("BAILIAN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

# Tavily配置
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")

# 学术搜索域名
ACADEMIC_DOMAINS = [
    "arxiv.org", "scholar.google.com", "dl.acm.org",
    "ieeexplore.ieee.org", "springer.com", "nature.com",
    "science.org", "semanticscholar.org", "pubmed.ncbi.nlm.nih.gov"
]


class PaperSegment:
    """论文片段数据结构"""
    
    def __init__(self, segment_id: int, title: str, content: str, 
                 segment_type: str, key_concepts: List[str], priority: int = 1):
        self.segment_id = segment_id
        self.title = title
        self.content = content
        self.segment_type = segment_type  # 如：background, method, experiment, discussion等
        self.key_concepts = key_concepts
        self.priority = priority  # 优先级：method=3, experiment=2, background=1
        self.search_queries: List[str] = []
        self.references: List[Dict] = []
    
    def to_dict(self) -> Dict:
        return {
            "segment_id": self.segment_id,
            "title": self.title,
            "content": self.content,
            "segment_type": self.segment_type,
            "key_concepts": self.key_concepts,
            "priority": self.priority,
            "search_queries": self.search_queries,
            "references": self.references
        }


class PaperReferenceSearcher:
    """论文参考文献搜索器"""
    
    # 片段类型优先级映射
    SEGMENT_PRIORITY = {
        "method": 3,
        "experiment": 2,
        "discussion": 2,
        "conclusion": 1,
        "background": 1,
        "other": 1
    }
    
    def __init__(self, config: Optional[SearchConfig] = None, 
                 refs_per_segment: Optional[int] = None):
        """
        初始化客户端
        
        Args:
            config: 搜索配置对象
            refs_per_segment: 每个片段返回的参考文献数量（向后兼容，不推荐使用）
        """
        if not BAILIAN_API_KEY:
            raise ValueError("请在.env文件中配置BAILIAN_API_KEY")
        if not TAVILY_API_KEY:
            raise ValueError("请在.env文件中配置TAVILY_API_KEY")
        
        # 兼容旧版本参数
        if config is None:
            config = SearchConfig()
            if refs_per_segment is not None:
                config.refs_per_segment = refs_per_segment
        
        self.config = config
        self.stats = ExecutionStats()
        
        # 初始化阿里云百炼客户端
        self.bailian_client = OpenAI(
            api_key=BAILIAN_API_KEY,
            base_url=BAILIAN_BASE_URL,
        )
        
        # 初始化Tavily客户端
        self.tavily_client = TavilyClient(api_key=TAVILY_API_KEY)
    
    def analyze_complexity(self, paper_content: str) -> int:
        """
        分析论文复杂度，返回推荐的片段数
        
        Args:
            paper_content: 论文内容
            
        Returns:
            推荐的片段数量
        """
        # 基于字数和段落数估算复杂度
        char_count = len(paper_content)
        paragraph_count = len([p for p in paper_content.split('\n\n') if p.strip()])
        
        # 复杂度评分：综合考虑字数和段落结构
        if char_count < 2000:
            complexity = 2
        elif char_count < 5000:
            complexity = min(4, 2 + paragraph_count // 3)
        elif char_count < 10000:
            complexity = min(6, 3 + paragraph_count // 2)
        else:
            complexity = min(10, 4 + paragraph_count // 2)
        
        return complexity
    
    def plan_with_budget(self, paper_content: str) -> Dict:
        """
        根据预算规划拆分方案
        
        Args:
            paper_content: 论文内容
            
        Returns:
            规划方案字典
        """
        complexity_score = self.analyze_complexity(paper_content)
        max_api_calls = self.config.max_api_calls
        
        if max_api_calls <= 10:
            # 低预算：合并为 2-3 个大片段，每片段 2-3 个查询
            segments = min(3, complexity_score)
            queries_per_segment = max(2, max_api_calls // segments)
        elif max_api_calls <= 30:
            # 中等预算：4-6 个片段，每片段 3-5 个查询
            segments = min(6, complexity_score)
            queries_per_segment = min(5, max_api_calls // segments)
        else:
            # 高预算：按论文自然结构拆分
            segments = complexity_score
            queries_per_segment = min(5, max_api_calls // segments)
        
        return {
            "segments": segments,
            "queries_per_segment": queries_per_segment,
            "estimated_calls": segments * queries_per_segment
        }
    
    def generate_plan_options(self, paper_content: str) -> List[Dict]:
        """
        生成多个方案供用户选择
        
        Args:
            paper_content: 论文内容
            
        Returns:
            方案列表
        """
        complexity = self.analyze_complexity(paper_content)
        
        return [
            {
                "name": "经济方案",
                "description": "快速检索核心文献，适合初步调研",
                "max_segments": 3,
                "queries_per_segment": 2,
                "estimated_calls": 6,
                "estimated_refs": 9
            },
            {
                "name": "标准方案",
                "description": "平衡覆盖度与成本，适合常规使用",
                "max_segments": min(5, complexity),
                "queries_per_segment": 3,
                "estimated_calls": min(15, complexity * 3),
                "estimated_refs": 15
            },
            {
                "name": "深度方案",
                "description": "全面检索相关文献，适合深入研究",
                "max_segments": min(8, complexity),
                "queries_per_segment": 4,
                "estimated_calls": min(32, complexity * 4),
                "estimated_refs": 24
            }
        ]
    
    def split_paper(self, paper_content: str, model: str = "qwen-plus",
                    max_segments: Optional[int] = None) -> List[PaperSegment]:
        """
        智能拆分论文为语义完整的片段
        
        Args:
            paper_content: 论文内容
            model: 使用的模型名称
            max_segments: 最大片段数量限制
            
        Returns:
            论文片段列表
        """
        # 如果没有指定 max_segments，根据模式计算
        if max_segments is None:
            if self.config.mode == SearchMode.BUDGET:
                plan = self.plan_with_budget(paper_content)
                max_segments = plan["segments"]
            elif self.config.mode == SearchMode.GRANULARITY:
                max_segments = self.config.max_segments
            else:
                max_segments = self.analyze_complexity(paper_content)
        
        system_prompt = f"""你是一位专业的学术论文分析专家。你的任务是将给定的论文内容智能拆分为多个语义完整的片段。

拆分原则：
1. 每个片段应该是一个独立的论述单元（如背景介绍、问题陈述、方法描述、实验说明、结果分析等）
2. 片段之间应该有清晰的语义边界
3. 保留每个片段的完整上下文，不要破坏论述的连贯性
4. 每个片段应该有明确的主题和可能需要引用文献的地方
5. **重要**：最多拆分为 {max_segments} 个片段，请合理合并相似内容

请以JSON格式返回拆分结果，格式如下：
{
    "segments": [
        {
            "title": "片段标题（简短描述该片段的主题）",
            "content": "片段的完整内容",
            "segment_type": "片段类型（background/method/experiment/discussion/conclusion/other）",
            "key_concepts": ["该片段涉及的关键概念或术语"]
        }
    ]
}

注意：
- 片段数量不超过 {max_segments} 个
- 每个片段的content应该是原文的完整段落，不要改写
- 如果论文内容较短，可以只拆分为2-3个片段
"""
        
        user_message = f"""请将以下论文内容智能拆分为语义完整的片段：

{paper_content}

请返回JSON格式的拆分结果。"""
        
        try:
            completion = self.bailian_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                response_format={"type": "json_object"}
            )
            
            result = json.loads(completion.choices[0].message.content)
            segments = []
            
            for i, seg_data in enumerate(result.get("segments", []), 1):
                segment = PaperSegment(
                    segment_id=i,
                    title=seg_data.get("title", f"片段{i}"),
                    content=seg_data.get("content", ""),
                    segment_type=seg_data.get("segment_type", "other"),
                    key_concepts=seg_data.get("key_concepts", [])
                )
                segments.append(segment)
            
            return segments
            
        except Exception as e:
            print(f"拆分论文时出错: {e}")
            # 降级处理：将整个论文作为一个片段
            return [PaperSegment(
                segment_id=1,
                title="完整论文",
                content=paper_content,
                segment_type="other",
                key_concepts=[]
            )]
    
    def analyze_segment(self, segment: PaperSegment, model: str = "qwen-plus",
                        max_queries: Optional[int] = None) -> List[str]:
        """
        分析单个片段，生成搜索查询
        
        Args:
            segment: 论文片段
            model: 使用的模型名称
            max_queries: 最大查询数量限制
            
        Returns:
            搜索查询列表
        """
        # 如果没有指定 max_queries，根据模式计算
        if max_queries is None:
            if self.config.mode == SearchMode.BUDGET:
                # 预算模式下，查询数由 plan_with_budget 决定
                max_queries = 5  # 默认值，实际由外部控制
            elif self.config.mode == SearchMode.GRANULARITY:
                max_queries = self.config.queries_per_segment
            else:
                max_queries = 5
        
        system_prompt = f"""你是一位专业的学术文献检索专家。你的任务是分析给定的论文片段，识别出该片段可能需要引用的参考文献，并生成精准的搜索查询。

分析要点：
1. 识别片段中提到的具体方法、模型、算法（可能需要引用原始论文）
2. 识别涉及的理论基础、经典概念（可能需要引用开创性工作）
3. 识别提到的数据集、工具、框架（可能需要引用来源）
4. 识别对比或参照的其他研究（可能需要引用相关论文）
5. 识别背景知识、领域共识（可能需要引用综述或经典文献）

请以JSON格式返回分析结果，格式如下：
{{
    "search_queries": [
        {{
            "query": "搜索查询语句（英文，便于在学术搜索引擎中使用）",
            "reason": "为什么需要搜索这个查询"
        }}
    ]
}}

要求：
- **重要**：最多生成 {max_queries} 个搜索查询
- 查询应该用英文，格式如："transformer attention mechanism original paper"
- 查询应该具体且有针对性，避免过于宽泛
- 每个查询都应该有明确的搜索目的
- 优先选择最重要的查询，不要为了凑数而生成低质量查询
"""
        
        user_message = f"""请分析以下论文片段，生成可能需要引用的文献的搜索查询：

片段标题：{segment.title}
片段类型：{segment.segment_type}
关键概念：{', '.join(segment.key_concepts) if segment.key_concepts else '无'}

片段内容：
{segment.content}

请返回JSON格式的分析结果。"""
        
        try:
            completion = self.bailian_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                response_format={"type": "json_object"}
            )
            
            result = json.loads(completion.choices[0].message.content)
            queries = []
            
            for item in result.get("search_queries", []):
                if item.get("query"):
                    queries.append(item["query"])
            
            return queries[:max_queries]
            
        except Exception as e:
            print(f"分析片段 {segment.segment_id} 时出错: {e}")
            # 降级处理：使用关键概念生成查询
            if segment.key_concepts:
                return [" ".join(segment.key_concepts[:3])]
            return []
    
    def search_references_for_segment(self, segment: PaperSegment, 
                                       queries: List[str]) -> List[Dict]:
        """
        为单个片段搜索参考文献
        
        Args:
            segment: 论文片段
            queries: 搜索查询列表
            
        Returns:
            参考文献列表
        """
        all_results = []
        seen_urls = set()
        
        for query in queries:
            try:
                self.stats.api_calls += 1
                results = self.tavily_client.search(
                    query=query,
                    search_depth="advanced",
                    max_results=self.config.refs_per_segment,
                    include_domains=ACADEMIC_DOMAINS
                )
                
                found_results = results.get("results", [])
                if not found_results:
                    self.stats.failed_calls += 1
                
                for result in found_results:
                    url = result.get("url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_results.append({
                            "title": result.get("title", ""),
                            "url": url,
                            "content": result.get("content", ""),
                            "score": result.get("score", 0),
                            "query": query
                        })
                        
            except Exception as e:
                print(f"搜索 '{query}' 时出错: {e}")
                self.stats.failed_calls += 1
        
        # 按相关性排序并限制数量
        all_results.sort(key=lambda x: x["score"], reverse=True)
        return all_results[:self.config.refs_per_segment]
    
    def search_paper_references(self, paper_content: str, 
                                 model: str = "qwen-plus",
                                 plan: Optional[Dict] = None) -> Dict:
        """
        完整的论文参考文献搜索流程
        
        Args:
            paper_content: 论文内容
            model: 使用的模型名称
            plan: 智能模式下的方案配置
            
        Returns:
            包含所有片段和参考文献的字典
        """
        # 重置统计
        self.stats = ExecutionStats()
        
        # 根据模式确定参数
        if plan:
            # 智能模式使用传入的方案
            max_segments = plan["max_segments"]
            queries_per_segment = plan["queries_per_segment"]
        elif self.config.mode == SearchMode.BUDGET:
            plan_result = self.plan_with_budget(paper_content)
            max_segments = plan_result["segments"]
            queries_per_segment = plan_result["queries_per_segment"]
            print(f"\n预计拆分 {max_segments} 个片段，每片段 {queries_per_segment} 个查询")
            print(f"预计 API 调用：{plan_result['estimated_calls']} 次")
        elif self.config.mode == SearchMode.GRANULARITY:
            max_segments = self.config.max_segments
            queries_per_segment = self.config.queries_per_segment
        else:
            max_segments = self.analyze_complexity(paper_content)
            queries_per_segment = 5
        
        print("=" * 70)
        print("步骤 1/3: 智能拆分论文...")
        print("=" * 70)
        
        # 拆分论文
        segments = self.split_paper(paper_content, model, max_segments)
        
        # 设置优先级
        for segment in segments:
            segment.priority = self.SEGMENT_PRIORITY.get(segment.segment_type, 1)
        
        # 按优先级排序（高优先级优先处理）
        segments.sort(key=lambda x: x.priority, reverse=True)
        
        # 重新分配 ID
        for i, segment in enumerate(segments, 1):
            segment.segment_id = i
        
        print(f"\n论文已拆分为 {len(segments)} 个片段")
        self.stats.segments_count = len(segments)
        
        print("\n" + "=" * 70)
        print("步骤 2/3: 分析各片段并生成搜索查询...")
        print("=" * 70)
        
        # 分析每个片段
        total_queries = 0
        for segment in segments:
            print(f"\n[片段 {segment.segment_id}] {segment.title}")
            print(f"  类型: {segment.segment_type}")
            print(f"  关键概念: {', '.join(segment.key_concepts) if segment.key_concepts else '无'}")
            
            queries = self.analyze_segment(segment, model, queries_per_segment)
            segment.search_queries = queries
            total_queries += len(queries)
            print(f"  生成查询: {queries}")
        
        self.stats.total_queries = total_queries
        
        print("\n" + "=" * 70)
        print("步骤 3/3: 搜索各片段的参考文献...")
        print("=" * 70)
        
        # 搜索每个片段的参考文献
        all_refs = []
        for segment in segments:
            print(f"\n[片段 {segment.segment_id}] 正在搜索...")
            references = self.search_references_for_segment(
                segment, segment.search_queries
            )
            segment.references = references
            all_refs.extend(references)
            print(f"  找到 {len(references)} 篇相关文献")
        
        # 统计信息
        unique_urls = set(ref["url"] for ref in all_refs)
        self.stats.total_refs = len(all_refs)
        self.stats.unique_refs = len(unique_urls)
        
        print(f"\n搜索完成！共找到 {self.stats.total_refs} 篇参考文献")
        print(self.stats.to_string())
        
        return {
            "segments": [seg.to_dict() for seg in segments],
            "summary": {
                "total_segments": len(segments),
                "total_references": self.stats.total_refs,
                "unique_references": self.stats.unique_refs,
                "refs_per_segment": self.config.refs_per_segment,
                "api_calls": self.stats.api_calls,
                "stats": {
                    "segments_count": self.stats.segments_count,
                    "total_queries": self.stats.total_queries,
                    "api_calls": self.stats.api_calls,
                    "failed_calls": self.stats.failed_calls
                }
            }
        }
    
    def format_results(self, results: Dict) -> str:
        """
        格式化输出结果
        
        Args:
            results: 搜索结果
            
        Returns:
            格式化的文本
        """
        output = []
        output.append("\n" + "=" * 70)
        output.append("论文参考文献搜索结果")
        output.append("=" * 70)
        
        summary = results.get("summary", {})
        output.append(f"\n共拆分为 {summary.get('total_segments', 0)} 个片段")
        output.append(f"共找到 {summary.get('total_references', 0)} 篇参考文献")
        output.append(f"去重后 {summary.get('unique_references', 0)} 篇")
        output.append(f"每个片段最多 {summary.get('refs_per_segment', 5)} 篇参考文献")
        
        stats = summary.get("stats", {})
        if stats:
            output.append(f"API 调用：{stats.get('api_calls', 0)} 次")
        
        for segment in results.get("segments", []):
            output.append("\n" + "-" * 70)
            output.append(f"## 片段 {segment['segment_id']}: {segment['title']}")
            output.append("-" * 70)
            output.append(f"类型: {segment['segment_type']}")
            output.append(f"关键概念: {', '.join(segment['key_concepts']) if segment['key_concepts'] else '无'}")
            
            # 显示片段内容摘要
            content = segment['content']
            if len(content) > 200:
                content = content[:200] + "..."
            output.append(f"\n内容摘要: {content}")
            
            # 显示搜索查询
            output.append(f"\n搜索查询:")
            for i, query in enumerate(segment['search_queries'], 1):
                output.append(f"  {i}. {query}")
            
            # 显示参考文献
            output.append(f"\n推荐参考文献 ({len(segment['references'])} 篇):")
            for i, ref in enumerate(segment['references'], 1):
                output.append(f"\n  [{i}] {ref['title']}")
                output.append(f"      URL: {ref['url']}")
                output.append(f"      相关性: {ref['score']:.2f}")
                output.append(f"      来源查询: {ref['query']}")
                # 摘要
                content = ref['content']
                if len(content) > 150:
                    content = content[:150] + "..."
                output.append(f"      摘要: {content}")
        
        return "\n".join(output)
    
    def format_markdown_results(self, results: Dict) -> str:
        """
        格式化为 Markdown 输出
        
        Args:
            results: 搜索结果
            
        Returns:
            Markdown 格式的文本
        """
        output = []
        output.append("# 论文参考文献搜索结果\n")
        
        summary = results.get("summary", {})
        output.append(f"> 共拆分为 **{summary.get('total_segments', 0)}** 个片段，")
        output.append(f"> 找到 **{summary.get('total_references', 0)}** 篇参考文献")
        output.append(f"> （去重后 **{summary.get('unique_references', 0)}** 篇）\n")
        
        stats = summary.get("stats", {})
        if stats:
            output.append(f"> API 调用：**{stats.get('api_calls', 0)}** 次\n")
        
        for segment in results.get("segments", []):
            output.append(f"\n## 片段 {segment['segment_id']}: {segment['title']}\n")
            output.append(f"- **类型**: {segment['segment_type']}")
            output.append(f"- **关键概念**: {', '.join(segment['key_concepts']) if segment['key_concepts'] else '无'}\n")
            
            # 片段内容
            content = segment['content']
            if len(content) > 300:
                content = content[:300] + "..."
            output.append(f"**内容摘要**:\n> {content}\n")
            
            # 参考文献
            output.append(f"**推荐参考文献** ({len(segment['references'])} 篇):\n")
            for i, ref in enumerate(segment['references'], 1):
                output.append(f"{i}. **{ref['title']}**")
                output.append(f"   - 链接: [{ref['url']}]({ref['url']})")
                output.append(f"   - 相关性: {ref['score']:.2f}")
                content = ref['content']
                if len(content) > 100:
                    content = content[:100] + "..."
                output.append(f"   - 摘要: {content}\n")
        
        return "\n".join(output)


def main():
    """主函数"""
    print("=" * 70)
    print("论文参考文献智能搜索工具")
    print("=" * 70)
    print("\n请输入论文内容（输入空行结束）:\n")
    
    # 读取多行输入
    lines = []
    while True:
        line = input()
        if line == "":
            break
        lines.append(line)
    
    paper_content = "\n".join(lines)
    
    if not paper_content.strip():
        print("未输入论文内容，程序退出")
        return
    
    # 选择搜索模式
    print("\n请选择搜索模式：")
    print("1. 预算驱动模式 - 指定 API 调用上限（推荐）")
    print("2. 粒度控制模式 - 手动设置参数")
    print("3. 智能规划模式 - AI 推荐方案")
    
    mode_choice = input("\n请选择 (1-3, 默认1): ").strip() or "1"
    
    config = SearchConfig()
    plan = None
    
    if mode_choice == "1":
        # 预算驱动模式
        config.mode = SearchMode.BUDGET
        max_calls = input("请输入最大 API 调用次数 (默认20): ").strip()
        config.max_api_calls = int(max_calls) if max_calls else 20
        config.refs_per_segment = 3
        
        # 显示预估
        searcher = PaperReferenceSearcher(config)
        plan_result = searcher.plan_with_budget(paper_content)
        print(f"\n预计拆分 {plan_result['segments']} 个片段，每片段 {plan_result['queries_per_segment']} 个查询")
        print(f"预计 API 调用：{plan_result['estimated_calls']} 次")
        
        confirm = input("是否继续？(y/n): ").strip().lower()
        if confirm != 'y':
            print("已取消")
            return
            
    elif mode_choice == "2":
        # 粒度控制模式
        config.mode = SearchMode.GRANULARITY
        
        max_segments = input("请输入最大片段数 (默认5): ").strip()
        config.max_segments = int(max_segments) if max_segments else 5
        
        queries = input("请输入每片段查询数 (默认2): ").strip()
        config.queries_per_segment = int(queries) if queries else 2
        
        refs = input("请输入每片段返回文献数 (默认3): ").strip()
        config.refs_per_segment = int(refs) if refs else 3
        
        estimated = config.max_segments * config.queries_per_segment
        print(f"\n预计 API 调用：{estimated} 次")
        
        confirm = input("是否继续？(y/n): ").strip().lower()
        if confirm != 'y':
            print("已取消")
            return
            
    elif mode_choice == "3":
        # 智能规划模式
        config.mode = SearchMode.SMART
        config.refs_per_segment = 3
        
        searcher = PaperReferenceSearcher(config)
        plans = searcher.generate_plan_options(paper_content)
        
        print("\nAI 为您推荐以下方案：")
        for i, p in enumerate(plans, 1):
            print(f"\n{i}. {p['name']}")
            print(f"   描述：{p['description']}")
            print(f"   片段数：{p['max_segments']}，每片段查询数：{p['queries_per_segment']}")
            print(f"   预计 API 调用：{p['estimated_calls']} 次")
            print(f"   预计返回文献：{p['estimated_refs']} 篇")
        
        plan_choice = input("\n请选择方案 (1-3): ").strip()
        if plan_choice in ["1", "2", "3"]:
            plan = plans[int(plan_choice) - 1]
        else:
            print("无效选择，使用标准方案")
            plan = plans[1]
    
    else:
        print("无效选择，使用默认预算驱动模式")
        config.mode = SearchMode.BUDGET
        config.max_api_calls = 20
        config.refs_per_segment = 3
    
    # 创建搜索器并执行搜索
    searcher = PaperReferenceSearcher(config)
    results = searcher.search_paper_references(paper_content, plan=plan)
    
    # 格式化输出
    print(searcher.format_results(results))
    
    # 可选：保存为 Markdown 文件
    save = input("\n是否保存结果为 Markdown 文件？(y/n): ")
    if save.lower() == 'y':
        filename = input("请输入文件名（默认: references.md）: ") or "references.md"
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(searcher.format_markdown_results(results))
        print(f"结果已保存到 {filename}")


if __name__ == "__main__":
    main()