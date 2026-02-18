"""
引用消息匹配器 - 智能匹配引用关系
"""
import re
from typing import List, Dict, Optional, Tuple


class QuoteMatcher:
    """引用消息匹配器 - 从候选消息中找到最匹配的被引用消息"""
    
    @staticmethod
    def clean_quote_text(quote: str) -> str:
        """
        清理引用文本，移除作者名、时间戳等元数据
        
        Args:
            quote: 原始引用文本
            
        Returns:
            清理后的引用文本
        """
        if not quote:
            return ""
        
        # 移除头像 fallback "X"（仅当开头是单独的 X，且后接非字母或结尾时；保留 "XOM" 等 ticker）
        text = re.sub(r'^[XＸ]+\s*(?=[^A-Za-z]|$)', '', quote)
        
        # 移除作者名模式: "xiaozhaolucky" 等（小写字母开头，后跟大写字母）
        # 例如: "xiaozhaoluckyGILD" -> "GILD"
        text = re.sub(r'^[a-z]+(?=[A-Z])', '', text)
        
        # 移除时间戳模式: "Jan 22, 2026 10:41 PM" 或 "•Jan 22, 2026"
        text = re.sub(r'[•·]?\s*[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}.*?[AP]M', '', text)
        text = re.sub(r'[•·]\s*[A-Z][a-z]{2}\s+\d{1,2}', '', text)
        
        # 移除多余空格
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text
    
    @staticmethod
    def extract_key_info(text: str) -> Dict[str, any]:
        """
        从文本中提取关键信息（股票代码、价格、操作方向等）
        
        Args:
            text: 消息文本
            
        Returns:
            包含关键信息的字典
        """
        info = {
            'symbols': [],  # 股票代码列表
            'prices': [],   # 价格列表
            'actions': [],  # 操作（买入/卖出）
            'keywords': []  # 其他关键词
        }
        
        # 提取股票代码（大写字母2-5个）
        symbols = re.findall(r'\b([A-Z]{2,5})\b', text)
        # 过滤掉常见的非股票代码词
        exclude_words = {'CALL', 'PUT', 'CALLS', 'PUTS', 'TAIL', 'PM', 'AM'}
        info['symbols'] = [s for s in symbols if s not in exclude_words]
        
        # 提取价格（$数字 或 数字.数字）
        prices = re.findall(r'\$?\d+\.?\d*', text)
        info['prices'] = prices
        
        # 识别操作方向
        if any(word in text.lower() for word in ['call', 'calls', '买', 'buy']):
            info['actions'].append('BUY')
        if any(word in text.lower() for word in ['put', 'puts', '出', '卖', 'sell']):
            info['actions'].append('SELL')
        if any(word in text.lower() for word in ['止损', 'stop']):
            info['actions'].append('STOP')
        
        # 提取其他关键词（长度>2的词）
        words = re.findall(r'\b\w{3,}\b', text)
        info['keywords'] = [w for w in words if not w.isdigit()]
        
        return info
    
    @staticmethod
    def calculate_similarity(quote_text: str, candidate_text: str) -> float:
        """
        计算引用文本与候选文本的相似度
        
        Args:
            quote_text: 引用文本
            candidate_text: 候选文本
            
        Returns:
            相似度得分 (0-1)
        """
        if not quote_text or not candidate_text:
            return 0.0
        
        # 提取关键信息
        quote_info = QuoteMatcher.extract_key_info(quote_text)
        candidate_info = QuoteMatcher.extract_key_info(candidate_text)
        
        score = 0.0
        
        # 1. 股票代码匹配（权重最高）
        if quote_info['symbols'] and candidate_info['symbols']:
            common_symbols = set(quote_info['symbols']) & set(candidate_info['symbols'])
            if common_symbols:
                score += 0.4  # 股票代码匹配得40分
        
        # 2. 价格匹配
        if quote_info['prices'] and candidate_info['prices']:
            common_prices = set(quote_info['prices']) & set(candidate_info['prices'])
            if common_prices:
                score += 0.2  # 价格匹配得20分
        
        # 3. 操作方向匹配
        if quote_info['actions'] and candidate_info['actions']:
            common_actions = set(quote_info['actions']) & set(candidate_info['actions'])
            if common_actions:
                score += 0.15  # 操作匹配得15分
        
        # 4. 关键词匹配
        if quote_info['keywords'] and candidate_info['keywords']:
            quote_kw_set = set(w.lower() for w in quote_info['keywords'][:10])
            candidate_kw_set = set(w.lower() for w in candidate_info['keywords'][:10])
            common_keywords = quote_kw_set & candidate_kw_set
            if common_keywords:
                # 根据匹配关键词的数量计算得分
                keyword_score = min(len(common_keywords) * 0.05, 0.15)
                score += keyword_score
        
        # 5. 文本包含关系（补充）
        quote_lower = quote_text.lower()
        candidate_lower = candidate_text.lower()
        
        # 检查引用文本的主要部分是否在候选文本中
        quote_parts = [p for p in quote_lower.split() if len(p) > 3]
        if quote_parts:
            match_count = sum(1 for part in quote_parts if part in candidate_lower)
            inclusion_score = (match_count / len(quote_parts)) * 0.1
            score += inclusion_score
        
        return min(score, 1.0)
    
    @classmethod
    def find_best_match(
        cls, 
        quote: str, 
        candidates: List[Dict],
        min_score: float = 0.3
    ) -> Optional[Dict]:
        """
        从候选消息中找到最匹配的被引用消息
        
        Args:
            quote: 引用文本
            candidates: 候选消息列表
            min_score: 最小相似度阈值
            
        Returns:
            最匹配的消息，如果没有找到则返回None
        """
        if not quote or not candidates:
            return None
        
        # 清理引用文本
        clean_quote = cls.clean_quote_text(quote)
        if len(clean_quote) < 5:
            return None
        
        # 计算每个候选消息的相似度
        scores = []
        for candidate in candidates:
            content = candidate.get('content', '')
            if not content:
                continue
            
            similarity = cls.calculate_similarity(clean_quote, content)
            if similarity >= min_score:
                scores.append((similarity, candidate))
        
        # 按相似度排序，返回最高分
        if scores:
            scores.sort(key=lambda x: x[0], reverse=True)
            return scores[0][1]
        
        return None
    
    @classmethod
    def match_with_context(
        cls,
        quote: str,
        candidates: List[Dict],
        author: str = "",
        date_part: List[str] = None,
        min_score: float = 0.3
    ) -> Optional[Dict]:
        """
        使用上下文信息进行匹配（作者、日期）
        
        Args:
            quote: 引用文本
            candidates: 候选消息列表
            author: 作者名
            date_part: 日期部分（用于筛选同一天的消息）
            min_score: 最小相似度阈值
            
        Returns:
            最匹配的消息
        """
        # 首先按上下文筛选候选消息
        filtered_candidates = []
        for candidate in candidates:
            # 如果有作者信息，优先匹配同一作者
            if author and candidate.get('author') == author:
                filtered_candidates.append(candidate)
                continue
            
            # 如果有日期信息，匹配同一天
            if date_part:
                candidate_date = candidate.get('timestamp', '').split()[:3]
                if candidate_date == date_part:
                    filtered_candidates.append(candidate)
                    continue
            
            # 如果没有上下文信息，包含所有候选
            if not author and not date_part:
                filtered_candidates.append(candidate)
        
        # 在筛选后的候选中查找最佳匹配
        if filtered_candidates:
            return cls.find_best_match(quote, filtered_candidates, min_score)
        
        # 如果筛选后没有结果，降低阈值在所有候选中查找
        return cls.find_best_match(quote, candidates, min_score * 0.8)