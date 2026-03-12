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
    bailian_calls: int = 0      # 百炼 API 调用次数
    tavily_calls: int = 0       # Tavily API 调用次数
    tavily_credits: int = 0     # Tavily API Credits 消耗（advanced 模式每次 2 Credits）
    failed_calls: int = 0
    total_refs: int = 0
    unique_refs: int = 0
    
    @property
    def api_calls(self) -> int:
        """总 API 调用次数（不包含 Credits 倍率）"""
        return self.bailian_calls + self.tavily_calls
    
    @property
    def total_credits(self) -> int:
        """总 Credits 消耗"""
        return self.bailian_calls + self.tavily_credits
    
    def to_string(self, monthly_limit: int = 1000) -> str:
        """格式化统计信息"""
        lines = [
            "========== 执行统计 ==========",
            f"片段数量：{self.segments_count}",
            f"总查询数：{self.total_queries}",
            f"API 调用：{self.api_calls} 次",
            f"  - 百炼 API：{self.bailian_calls} 次（论文拆分 + 片段分析）",
            f"  - Tavily API：{self.tavily_calls} 次（文献搜索，advanced 模式）",
            f"Credits 消耗：{self.total_credits}",
            f"  - 百炼 API：{self.bailian_calls} Credits",
            f"  - Tavily API：{self.tavily_credits} Credits（advanced 模式每次 2 Credits）",
        ]
        if self.failed_calls > 0:
            lines.append(f"  （{self.failed_calls} 个查询无结果）")
        lines.append(f"返回文献：{self.total_refs} 篇（去重后 {self.unique_refs} 篇）")
        if self.total_credits > 0:
            percentage = (self.total_credits / monthly_limit) * 100
            lines.append(f"预估成本：{self.total_credits}/{monthly_limit} ({percentage:.1f}%)")
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
    
    def _generate_citation(self, ref: Dict, index: int) -> str:
        """
        生成参考文献的引用格式
        
        根据中国国家标准 GB/T 7714-2015 生成引用格式
        
        Args:
            ref: 参考文献信息字典
            index: 引用序号
            
        Returns:
            格式化的引用字符串
        """
        title = ref.get('title', '未知标题')
        url = ref.get('url', '')
        
        # 尝试从 URL 提取来源信息
        source = "网络资源"
        if url:
            try:
                from urllib.parse import urlparse
                domain = urlparse(url).netloc
                # 常见学术网站映射
                domain_map = {
                    'arxiv.org': 'arXiv',
                    'scholar.google.com': 'Google Scholar',
                    'dl.acm.org': 'ACM Digital Library',
                    'ieeexplore.ieee.org': 'IEEE Xplore',
                    'springer.com': 'Springer',
                    'nature.com': 'Nature',
                    'science.org': 'Science',
                    'semanticscholar.org': 'Semantic Scholar',
                    'pubmed.ncbi.nlm.nih.gov': 'PubMed'
                }
                source = domain_map.get(domain, domain)
            except:
                pass
        
        # 生成引用格式：[序号] 标题[来源类型]. 来源, 访问日期.
        from datetime import datetime
        access_date = datetime.now().strftime('%Y-%m-%d')
        
        # 判断来源类型
        if 'arxiv' in url.lower():
            citation = f"[{index}] {title}[EB/OL]. arXiv预印本, {access_date}. {url}"
        elif any(d in url.lower() for d in ['scholar.google', 'semanticscholar']):
            citation = f"[{index}] {title}[EB/OL]. {source}, {access_date}. {url}"
        else:
            citation = f"[{index}] {title}[EB/OL]. {source}, {access_date}. {url}"
        
        return citation
    
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
        
        # 预估公式（按 Credits 计算）：
        # total_credits = 1 + segments + segments * queries_per_segment * 2
        # 其中：1 = 论文拆分（百炼），segments = 片段分析（百炼），
        #       segments * queries * 2 = 文献搜索（Tavily advanced 模式每次 2 Credits）
        
        # 简化计算：假设 segments 和 queries 的合理组合
        if max_api_calls <= 10:
            # 低预算：合并为 2-3 个大片段，每片段 1-2 个查询
            segments = min(3, complexity_score)
            # 反推 queries_per_segment：(max - 1 - segments) / (segments * 2)
            queries_per_segment = max(1, (max_api_calls - 1 - segments) // (segments * 2))
        elif max_api_calls <= 30:
            # 中等预算：4-6 个片段，每片段 2-3 个查询
            segments = min(6, complexity_score)
            queries_per_segment = min(3, max(1, (max_api_calls - 1 - segments) // (segments * 2)))
        else:
            # 高预算：按论文自然结构拆分
            segments = complexity_score
            queries_per_segment = min(4, max(1, (max_api_calls - 1 - segments) // (segments * 2)))
        
        # 计算预估
        bailian_calls = 1 + segments  # 论文拆分 + 片段分析
        tavily_calls = segments * queries_per_segment  # Tavily 调用次数
        tavily_credits = tavily_calls * 2  # Tavily advanced 模式每次 2 Credits
        estimated_credits = bailian_calls + tavily_credits
        
        return {
            "segments": segments,
            "queries_per_segment": queries_per_segment,
            "estimated_calls": bailian_calls + tavily_calls,  # 调用次数
            "estimated_credits": estimated_credits,  # Credits 消耗
            "bailian_calls": bailian_calls,
            "tavily_calls": tavily_calls,
            "tavily_credits": tavily_credits
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
        
        # 预估公式（按 Credits 计算）：
        # estimated_credits = 1 + segments + segments * queries_per_segment * 2
        # 1 = 论文拆分（百炼），segments = 片段分析（百炼），
        # segments * queries * 2 = 文献搜索（Tavily advanced 模式每次 2 Credits）
        
        economy_segments = 3
        economy_queries = 2
        standard_segments = min(5, complexity)
        standard_queries = 3
        deep_segments = min(8, complexity)
        deep_queries = 4
        
        # 计算 Credits
        economy_bailian = 1 + economy_segments
        economy_tavily_credits = economy_segments * economy_queries * 2
        standard_bailian = 1 + standard_segments
        standard_tavily_credits = standard_segments * standard_queries * 2
        deep_bailian = 1 + deep_segments
        deep_tavily_credits = deep_segments * deep_queries * 2
        
        return [
            {
                "name": "经济方案",
                "description": "快速检索核心文献，适合初步调研",
                "max_segments": economy_segments,
                "queries_per_segment": economy_queries,
                "estimated_calls": economy_bailian + economy_segments * economy_queries,
                "estimated_credits": economy_bailian + economy_tavily_credits,
                "tavily_credits": economy_tavily_credits,
                "estimated_refs": 9
            },
            {
                "name": "标准方案",
                "description": "平衡覆盖度与成本，适合常规使用",
                "max_segments": standard_segments,
                "queries_per_segment": standard_queries,
                "estimated_calls": standard_bailian + standard_segments * standard_queries,
                "estimated_credits": standard_bailian + standard_tavily_credits,
                "tavily_credits": standard_tavily_credits,
                "estimated_refs": 15
            },
            {
                "name": "深度方案",
                "description": "全面检索相关文献，适合深入研究",
                "max_segments": deep_segments,
                "queries_per_segment": deep_queries,
                "estimated_calls": deep_bailian + deep_segments * deep_queries,
                "estimated_credits": deep_bailian + deep_tavily_credits,
                "tavily_credits": deep_tavily_credits,
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
{{
    "segments": [
        {{
            "title": "片段标题（简短描述该片段的主题）",
            "content": "片段的完整内容",
            "segment_type": "片段类型（background/method/experiment/discussion/conclusion/other）",
            "key_concepts": ["该片段涉及的关键概念或术语"]
        }}
    ]
}}

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
            
            # 统计百炼 API 调用
            self.stats.bailian_calls += 1
            
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
            
            # 统计百炼 API 调用
            self.stats.bailian_calls += 1
            
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
                self.stats.tavily_calls += 1
                self.stats.tavily_credits += 2  # Tavily advanced 模式每次消耗 2 Credits
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
            print(f"  - 百炼 API：{plan_result['bailian_calls']} 次（论文拆分 1 + 片段分析 {max_segments}）")
            print(f"  - Tavily API：{plan_result['tavily_calls']} 次（文献搜索，advanced 模式）")
            print(f"预计 Credits 消耗：{plan_result['estimated_credits']}")
            print(f"  - 百炼 API：{plan_result['bailian_calls']} Credits")
            print(f"  - Tavily API：{plan_result['tavily_credits']} Credits（advanced 模式每次 2 Credits）")
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
            "original_content": paper_content,  # 原始论文内容
            "segments": [seg.to_dict() for seg in segments],
            "summary": {
                "total_segments": len(segments),
                "total_references": self.stats.total_refs,
                "unique_references": self.stats.unique_refs,
                "refs_per_segment": self.config.refs_per_segment,
                "api_calls": self.stats.api_calls,
                "total_credits": self.stats.total_credits,
                "stats": {
                    "segments_count": self.stats.segments_count,
                    "total_queries": self.stats.total_queries,
                    "api_calls": self.stats.api_calls,
                    "bailian_calls": self.stats.bailian_calls,
                    "tavily_calls": self.stats.tavily_calls,
                    "tavily_credits": self.stats.tavily_credits,
                    "total_credits": self.stats.total_credits,
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
        
        # 显示原始论文内容
        original_content = results.get("original_content", "")
        if original_content:
            output.append("\n" + "-" * 70)
            output.append("原始论文内容")
            output.append("-" * 70)
            output.append(original_content)
        
        summary = results.get("summary", {})
        output.append("\n" + "-" * 70)
        output.append("搜索结果摘要")
        output.append("-" * 70)
        output.append(f"共拆分为 {summary.get('total_segments', 0)} 个片段")
        output.append(f"共找到 {summary.get('total_references', 0)} 篇参考文献")
        output.append(f"去重后 {summary.get('unique_references', 0)} 篇")
        output.append(f"每个片段最多 {summary.get('refs_per_segment', 5)} 篇参考文献")
        
        stats = summary.get("stats", {})
        if stats:
            output.append(f"API 调用：{stats.get('api_calls', 0)} 次")
            output.append(f"  - 百炼 API：{stats.get('bailian_calls', 0)} 次")
            output.append(f"  - Tavily API：{stats.get('tavily_calls', 0)} 次（advanced 模式）")
            output.append(f"Credits 消耗：{stats.get('total_credits', 0)}")
            output.append(f"  - 百炼 API：{stats.get('bailian_calls', 0)} Credits")
            output.append(f"  - Tavily API：{stats.get('tavily_credits', 0)} Credits（每次 2 Credits）")
        
        for segment in results.get("segments", []):
            output.append("\n" + "-" * 70)
            output.append(f"## 片段 {segment['segment_id']}: {segment['title']}")
            output.append("-" * 70)
            output.append(f"类型: {segment['segment_type']}")
            output.append(f"关键概念: {', '.join(segment['key_concepts']) if segment['key_concepts'] else '无'}")
            
            # 显示片段内容（完整显示，不截断）
            output.append(f"\n片段内容:\n{segment['content']}")
            
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
                # 引用格式
                citation = self._generate_citation(ref, i)
                output.append(f"      引用格式: {citation}")
                # # 摘要（完整显示，不截断）
                # output.append(f"      摘要: {ref['content']}")
        
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
        
        # 显示原始论文内容
        original_content = results.get("original_content", "")
        if original_content:
            output.append("## 原始论文内容\n")
            output.append("```")
            output.append(original_content)
            output.append("```\n")
        
        summary = results.get("summary", {})
        output.append("## 搜索结果摘要\n")
        output.append(f"> 共拆分为 **{summary.get('total_segments', 0)}** 个片段，")
        output.append(f"> 找到 **{summary.get('total_references', 0)}** 篇参考文献")
        output.append(f"> （去重后 **{summary.get('unique_references', 0)}** 篇）\n")
        
        stats = summary.get("stats", {})
        if stats:
            output.append(f"> API 调用：**{stats.get('api_calls', 0)}** 次")
            output.append(f"> - 百炼 API：**{stats.get('bailian_calls', 0)}** 次")
            output.append(f"> - Tavily API：**{stats.get('tavily_calls', 0)}** 次（advanced 模式）")
            output.append(f"> Credits 消耗：**{stats.get('total_credits', 0)}**")
            output.append(f"> - 百炼 API：**{stats.get('bailian_calls', 0)}** Credits")
            output.append(f"> - Tavily API：**{stats.get('tavily_credits', 0)}** Credits（每次 2 Credits）\n")
        
        for segment in results.get("segments", []):
            output.append(f"\n## 片段 {segment['segment_id']}: {segment['title']}\n")
            output.append(f"- **类型**: {segment['segment_type']}")
            output.append(f"- **关键概念**: {', '.join(segment['key_concepts']) if segment['key_concepts'] else '无'}\n")
            
            # 片段内容（完整显示，不截断）
            output.append(f"**片段内容**:\n```\n{segment['content']}\n```\n")
            
            # 参考文献
            output.append(f"**推荐参考文献** ({len(segment['references'])} 篇):\n")
            for i, ref in enumerate(segment['references'], 1):
                output.append(f"{i}. **{ref['title']}**")
                output.append(f"   - 链接: [{ref['url']}]({ref['url']})")
                output.append(f"   - 相关性: {ref['score']:.2f}")
                # 引用格式
                citation = self._generate_citation(ref, i)
                output.append(f"   - 引用格式: {citation}")
                # # 摘要（完整显示，不截断）
                # output.append(f"   - 摘要: {ref['content']}\n")
        
        return "\n".join(output)


# ==================== 输入校验工具函数 ====================

class InputResult:
    """输入结果"""
    BACK = "back"      # 用户选择回退
    QUIT = "quit"      # 用户选择退出
    VALUE = "value"    # 有效值


def get_valid_input(prompt: str,
                    validator: callable,
                    default: str = None,
                    allow_back: bool = False,
                    allow_quit: bool = False) -> tuple:
    """
    获取有效输入
    
    Args:
        prompt: 提示信息
        validator: 校验函数，返回 (is_valid, converted_value, error_msg)
        default: 默认值
        allow_back: 是否允许回退
        allow_quit: 是否允许退出
    
    Returns:
        (result_type, value): 结果类型和值
    """
    while True:
        try:
            user_input = input(prompt).strip()
        except EOFError:
            return InputResult.QUIT, None
        
        # 检查退出命令
        if allow_quit and user_input.lower() in ['q', 'quit', 'exit']:
            return InputResult.QUIT, None
        
        # 检查回退命令
        if allow_back and user_input.lower() in ['b', 'back']:
            return InputResult.BACK, None
        
        # 检查默认值
        if not user_input and default is not None:
            return InputResult.VALUE, default
        
        # 校验
        is_valid, value, error_msg = validator(user_input)
        if is_valid:
            return InputResult.VALUE, value
        
        print(f"输入无效: {error_msg}，请重新输入")


def validate_choice(min_val: int, max_val: int):
    """创建选项校验器"""
    def validator(user_input: str):
        if not user_input:
            return False, None, f"请输入 {min_val}-{max_val} 的数字"
        try:
            value = int(user_input)
            if min_val <= value <= max_val:
                return True, value, ""
            return False, None, f"请输入 {min_val}-{max_val} 的数字"
        except ValueError:
            return False, None, "请输入有效的数字"
    return validator


def validate_positive_int(min_val: int = 1, max_val: int = 100):
    """创建正整数校验器"""
    def validator(user_input: str):
        if not user_input:
            return False, None, "请输入一个数字"
        try:
            value = int(user_input)
            if min_val <= value <= max_val:
                return True, value, ""
            return False, None, f"请输入 {min_val}-{max_val} 之间的整数"
        except ValueError:
            return False, None, "请输入有效的整数"
    return validator


def validate_yes_no():
    """创建是/否校验器"""
    def validator(user_input: str):
        if user_input.lower() in ['y', 'yes', '是']:
            return True, True, ""
        if user_input.lower() in ['n', 'no', '否']:
            return True, False, ""
        return False, None, "请输入 y 或 n"
    return validator


def get_paper_input() -> Optional[str]:
    """
    获取论文内容输入
    
    Returns:
        论文内容，如果用户选择退出则返回 None
    """
    print("\n请输入论文内容（输入空行结束，输入 q 退出）:\n")
    
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            return None
        
        # 检查退出命令
        if line.lower() in ['q', 'quit', 'exit']:
            return None
        
        # 空行结束输入
        if line == "":
            break
        
        lines.append(line)
    
    return "\n".join(lines)


def main():
    """主函数"""
    print("=" * 70)
    print("论文参考文献智能搜索工具")
    print("=" * 70)
    print("\n提示：在任意输入步骤，输入 'q' 退出程序")
    
    # 主循环：允许用户连续处理多篇论文
    while True:
        # ========== 步骤 1：输入论文内容 ==========
        paper_content = get_paper_input()
        
        if paper_content is None:
            print("\n感谢使用，再见！")
            return
        
        if not paper_content.strip():
            print("未输入论文内容，请重新输入")
            continue
        
        # ========== 步骤 2：选择模式和配置参数 ==========
        config = SearchConfig()
        plan = None
        
        # 模式选择循环
        while True:
            print("\n" + "-" * 40)
            print("请选择搜索模式：")
            print("1. 预算驱动模式 - 指定 API 调用上限（推荐）")
            print("2. 粒度控制模式 - 手动设置参数")
            print("3. 智能规划模式 - 预设方案（AI规划暂未实现）")
            
            result, mode_choice = get_valid_input(
                prompt="\n请选择 (1-3, 默认1): ",
                validator=validate_choice(1, 3),
                default="1",
                allow_quit=True
            )
            
            if result == InputResult.QUIT:
                print("\n感谢使用，再见！")
                return
            
            # ========== 预算驱动模式 ==========
            if mode_choice == 1:
                config.mode = SearchMode.BUDGET
                
                # 输入 API 调用次数
                while True:
                    result, max_calls = get_valid_input(
                        prompt="请输入最大 API 调用次数 (5-100, 默认20): ",
                        validator=validate_positive_int(5, 100),
                        default="20",
                        allow_back=True,
                        allow_quit=True
                    )
                    
                    if result == InputResult.QUIT:
                        print("\n感谢使用，再见！")
                        return
                    if result == InputResult.BACK:
                        break  # 返回模式选择
                    
                    config.max_api_calls = max_calls
                    config.refs_per_segment = 3
                    
                    # 显示预估
                    try:
                        searcher = PaperReferenceSearcher(config)
                        plan_result = searcher.plan_with_budget(paper_content)
                        print(f"\n预计拆分 {plan_result['segments']} 个片段，每片段 {plan_result['queries_per_segment']} 个查询")
                        print(f"预计 API 调用：{plan_result['estimated_calls']} 次")
                    except ValueError as e:
                        print(f"配置错误: {e}")
                        continue
                    
                    # 确认执行
                    result, confirm = get_valid_input(
                        prompt="是否继续？(y/n): ",
                        validator=validate_yes_no(),
                        allow_back=True,
                        allow_quit=True
                    )
                    
                    if result == InputResult.QUIT:
                        print("\n感谢使用，再见！")
                        return
                    if result == InputResult.BACK:
                        continue  # 重新输入参数
                    
                    if confirm:
                        break  # 继续执行
                    else:
                        print("已取消，返回模式选择...")
                        break  # 返回模式选择
                
                # 如果用户取消了，重新选择模式
                if not confirm:
                    continue
                else:
                    break  # 继续执行搜索
            
            # ========== 粒度控制模式 ==========
            elif mode_choice == 2:
                config.mode = SearchMode.GRANULARITY
                
                # 输入参数循环
                params_confirmed = False
                while not params_confirmed:
                    # 最大片段数
                    result, max_segments = get_valid_input(
                        prompt="请输入最大片段数 (1-20, 默认5): ",
                        validator=validate_positive_int(1, 20),
                        default="5",
                        allow_back=True,
                        allow_quit=True
                    )
                    
                    if result == InputResult.QUIT:
                        print("\n感谢使用，再见！")
                        return
                    if result == InputResult.BACK:
                        break  # 返回模式选择
                    
                    config.max_segments = max_segments
                    
                    # 每片段查询数
                    result, queries = get_valid_input(
                        prompt="请输入每片段查询数 (1-10, 默认2): ",
                        validator=validate_positive_int(1, 10),
                        default="2",
                        allow_back=True,
                        allow_quit=True
                    )
                    
                    if result == InputResult.QUIT:
                        print("\n感谢使用，再见！")
                        return
                    if result == InputResult.BACK:
                        continue  # 重新输入参数
                    
                    config.queries_per_segment = queries
                    
                    # 每片段文献数
                    result, refs = get_valid_input(
                        prompt="请输入每片段返回文献数 (1-10, 默认3): ",
                        validator=validate_positive_int(1, 10),
                        default="3",
                        allow_back=True,
                        allow_quit=True
                    )
                    
                    if result == InputResult.QUIT:
                        print("\n感谢使用，再见！")
                        return
                    if result == InputResult.BACK:
                        continue  # 重新输入参数
                    
                    config.refs_per_segment = refs
                    
                    # 显示预估
                    estimated = config.max_segments * config.queries_per_segment
                    print(f"\n预计 API 调用：{estimated} 次")
                    
                    # 确认执行
                    result, confirm = get_valid_input(
                        prompt="是否继续？(y/n): ",
                        validator=validate_yes_no(),
                        allow_back=True,
                        allow_quit=True
                    )
                    
                    if result == InputResult.QUIT:
                        print("\n感谢使用，再见！")
                        return
                    if result == InputResult.BACK:
                        continue  # 重新输入参数
                    
                    if confirm:
                        params_confirmed = True
                    else:
                        print("已取消，返回模式选择...")
                        break  # 返回模式选择
                
                if not params_confirmed:
                    continue  # 返回模式选择
                else:
                    break  # 继续执行搜索
            
            # ========== 智能规划模式 ==========
            elif mode_choice == 3:
                config.mode = SearchMode.SMART
                config.refs_per_segment = 3
                
                try:
                    searcher = PaperReferenceSearcher(config)
                    plans = searcher.generate_plan_options(paper_content)
                except ValueError as e:
                    print(f"初始化错误: {e}")
                    continue
                
                # 方案选择循环
                while True:
                    print("\nAI 为您推荐以下方案：")
                    for i, p in enumerate(plans, 1):
                        print(f"\n{i}. {p['name']}")
                        print(f"   描述：{p['description']}")
                        print(f"   片段数：{p['max_segments']}，每片段查询数：{p['queries_per_segment']}")
                        print(f"   预计 API 调用：{p['estimated_calls']} 次")
                        print(f"   预计 Credits 消耗：{p['estimated_credits']}（Tavily 每次 2 Credits）")
                        print(f"   预计返回文献：{p['estimated_refs']} 篇")
                    
                    result, plan_choice = get_valid_input(
                        prompt="\n请选择方案 (1-3): ",
                        validator=validate_choice(1, 3),
                        allow_back=True,
                        allow_quit=True
                    )
                    
                    if result == InputResult.QUIT:
                        print("\n感谢使用，再见！")
                        return
                    if result == InputResult.BACK:
                        break  # 返回模式选择
                    
                    plan = plans[plan_choice - 1]
                    
                    # 确认执行
                    result, confirm = get_valid_input(
                        prompt=f"已选择「{plan['name']}」，是否继续？(y/n): ",
                        validator=validate_yes_no(),
                        allow_back=True,
                        allow_quit=True
                    )
                    
                    if result == InputResult.QUIT:
                        print("\n感谢使用，再见！")
                        return
                    if result == InputResult.BACK:
                        continue  # 重新选择方案
                    
                    if confirm:
                        break  # 继续执行搜索
                    else:
                        print("已取消，返回模式选择...")
                        break
                
                if plan is None or not confirm:
                    continue  # 返回模式选择
                else:
                    break  # 继续执行搜索
        
        # ========== 步骤 3：执行搜索 ==========
        try:
            searcher = PaperReferenceSearcher(config)
            results = searcher.search_paper_references(paper_content, plan=plan)
        except ValueError as e:
            print(f"执行错误: {e}")
            continue
        
        # 格式化输出
        print(searcher.format_results(results))
        
        # ========== 步骤 4：保存结果 ==========
        result, save = get_valid_input(
            prompt="\n是否保存结果为 Markdown 文件？(y/n): ",
            validator=validate_yes_no(),
            allow_quit=True
        )
        
        if result == InputResult.QUIT:
            print("\n感谢使用，再见！")
            return
        
        if save:
            result, filename = get_valid_input(
                prompt="请输入文件名（默认: references.md）: ",
                validator=lambda x: (True, x if x else "references.md", ""),
                default="references.md",
                allow_quit=True
            )
            
            if result == InputResult.QUIT:
                print("\n感谢使用，再见！")
                return
            
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(searcher.format_markdown_results(results))
                print(f"结果已保存到 {filename}")
            except IOError as e:
                print(f"保存失败: {e}")
        
        # ========== 步骤 5：询问是否继续 ==========
        result, continue_search = get_valid_input(
            prompt="\n是否继续处理下一篇论文？(y/n): ",
            validator=validate_yes_no(),
            allow_quit=True
        )
        
        if result == InputResult.QUIT or not continue_search:
            print("\n感谢使用，再见！")
            return
        
        print("\n" + "=" * 70)
        print("开始处理新论文...")
        print("=" * 70)


if __name__ == "__main__":
    main()