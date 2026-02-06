"""
消息上下文解析器
利用消息的 history、refer 字段和全局消息列表来补全期权指令中缺失的信息
解析时统一将到期日转为 YYMMDD，并在信息完整时生成期权代码 symbol。
"""
import os
from typing import Optional, List, Dict, Tuple
from parser.option_parser import OptionParser
from models.instruction import OptionInstruction, InstructionType


class MessageContextResolver:
    """
    消息上下文解析器
    负责利用历史消息、引用消息补全期权指令的缺失信息
    """
    
    def __init__(self, all_messages: List[dict]):
        """
        初始化解析器
        
        Args:
            all_messages: 所有消息的 simple_dict 格式列表
                每个消息包含: domID, content, timestamp, refer, position, history
        """
        self.all_messages = all_messages
        # 创建消息索引，方便快速定位
        self.message_index = {msg['domID']: idx for idx, msg in enumerate(all_messages)}
        # 从环境变量读取上下文查找范围（默认5条）
        self.context_search_limit = int(os.getenv('CONTEXT_SEARCH_LIMIT', '10'))
        
    def resolve_instruction(self, message_dict: dict) -> Optional[Tuple[OptionInstruction, Optional[str], Optional[str]]]:
        """
        解析消息并补全上下文
        
        Args:
            message_dict: 消息的 simple_dict 格式
            
        Returns:
            (instruction, context_source, context_message) 或 None
            - instruction: 解析后的指令
            - context_source: 上下文来源 ("history" / "refer" / "前N条" / None)
            - context_message: 用于补全的上下文消息内容
        """
        content = message_dict.get('content', '').strip()
        timestamp = message_dict.get('timestamp')
        
        if not content or len(content) < 2:
            return None
        
        # 1. 使用基础解析器解析当前消息
        instruction = OptionParser.parse(content, 
                                        message_id=message_dict.get('domID'),
                                        message_timestamp=timestamp)
        
        if not instruction:
            return None
        
        # 2. 检查是否需要补全
        if not self._needs_completion(instruction):
            self._finalize_instruction(instruction, message_dict)
            return (instruction, None, None)
        
        # 3. 根据策略查找上下文
        context_info = None
        if instruction.ticker:
            # 积极策略：有ticker但缺细节
            context_info = self._find_context_aggressive(message_dict, instruction.ticker)
        else:
            # 保守策略：无ticker
            context_info = self._find_context_conservative(message_dict)
        
        if not context_info:
            return (instruction, None, None)
        
        # 4. 应用上下文补全
        completed_instruction = self._apply_context(instruction, context_info['context'])
        completed_instruction.source = context_info['source']
        completed_instruction.depend_message = context_info['message']
        completed_instruction.origin = message_dict
        self._finalize_instruction(completed_instruction, message_dict)
        return (completed_instruction, context_info['source'], context_info['message'])
    
    def _needs_completion(self, instruction: OptionInstruction) -> bool:
        """
        判断指令是否需要补全
        
        Args:
            instruction: 已解析的指令
            
        Returns:
            True 如果需要补全，False 否则
        """
        # BUY 指令通常信息完整，不需要补全
        if instruction.instruction_type == InstructionType.BUY.value:
            return False
        
        # SELL/CLOSE/MODIFY 指令检查是否缺少关键信息
        if instruction.instruction_type in [InstructionType.SELL.value, 
                                           InstructionType.CLOSE.value, 
                                           InstructionType.MODIFY.value]:
            # 缺少 ticker 或（有ticker但缺少strike/expiry）
            return (not instruction.ticker or 
                   not instruction.strike or 
                   not instruction.expiry)
        
        return False

    def _finalize_instruction(self, instruction: OptionInstruction, message_dict: dict) -> None:
        """
        解析收尾：将到期日统一转为 YYMMDD，并在信息完整时生成期权代码。
        """
        timestamp = message_dict.get("timestamp")
        if instruction.expiry:
            normalized = OptionInstruction.normalize_expiry_to_yymmdd(
                instruction.expiry, timestamp
            )
            if normalized:
                instruction.expiry = normalized
        if not instruction.symbol and all(
            [instruction.ticker, instruction.option_type, instruction.strike, instruction.expiry]
        ):
            instruction.symbol = OptionInstruction.generate_option_symbol(
                instruction.ticker,
                instruction.option_type,
                instruction.strike,
                instruction.expiry,
                timestamp,
            )

    def _find_context_aggressive(self, message_dict: dict, ticker: str) -> Optional[Dict]:
        """
        积极查找策略：有ticker但缺细节
        
        查找顺序（所有查找都必须精确匹配ticker）：
        1. history 字段（同组历史消息）- 精确匹配ticker
        2. refer 字段（引用消息）- 精确匹配ticker
        3. 前N条消息（全局列表，N由CONTEXT_SEARCH_LIMIT配置）- 精确匹配ticker
        
        Args:
            message_dict: 当前消息
            ticker: 股票代码
            
        Returns:
            {'context': {...}, 'source': str, 'message': str} 或 None
        """
        timestamp = message_dict.get('timestamp')
        
        # 1. 查找 history（精确匹配ticker）
        history = message_dict.get('history', [])
        if history:
            context = self._search_in_history(history, ticker, timestamp)
            if context:
                return {
                    'context': context,
                    'source': 'history',
                    'message': context.get('raw_message', '')
                }
        
        # 2. 查找 refer（精确匹配ticker）
        refer = message_dict.get('refer')
        if refer:
            context = self._search_in_refer(refer, ticker, timestamp)
            if context:
                return {
                    'context': context,
                    'source': 'refer',
                    'message': refer
                }
        
        # 3. 查找前N条消息（精确匹配ticker）
        dom_id = message_dict.get('domID')
        if dom_id:
            context = self._search_in_recent_messages(dom_id, ticker, limit=self.context_search_limit)
            if context:
                return {
                    'context': context,
                    'source': f'前{self.context_search_limit}条',
                    'message': context.get('raw_message', '')
                }
        
        return None
    
    def _find_context_conservative(self, message_dict: dict) -> Optional[Dict]:
        """
        保守查找策略：无ticker
        
        查找顺序：
        1. history 字段
        2. refer 字段
        3. 前N条消息（全局列表，N由CONTEXT_SEARCH_LIMIT配置）- 查找最近的任意BUY指令
        
        Args:
            message_dict: 当前消息
            
        Returns:
            {'context': {...}, 'source': str, 'message': str} 或 None
        """
        timestamp = message_dict.get('timestamp')
        
        # 1. 查找 history
        history = message_dict.get('history', [])
        if history:
            context = self._search_in_history(history, ticker=None, message_timestamp=timestamp)
            if context:
                return {
                    'context': context,
                    'source': 'history',
                    'message': context.get('raw_message', '')
                }
        
        # 2. 查找 refer
        refer = message_dict.get('refer')
        if refer:
            context = self._search_in_refer(refer, ticker=None, message_timestamp=timestamp)
            if context:
                return {
                    'context': context,
                    'source': 'refer',
                    'message': refer
                }
        
        # 3. 查找前N条消息（不指定ticker，查找最近的任意BUY指令）
        dom_id = message_dict.get('domID')
        if dom_id:
            context = self._search_in_recent_messages(dom_id, ticker=None, limit=self.context_search_limit)
            if context:
                return {
                    'context': context,
                    'source': f'前{self.context_search_limit}条',
                    'message': context.get('raw_message', '')
                }
        
        return None
    
    def _search_in_history(self, history: List[str], ticker: Optional[str], message_timestamp: Optional[str] = None) -> Optional[Dict]:
        """
        在 history 列表中查找最近的 BUY 指令
        
        Args:
            history: 历史消息列表（按时间顺序，最新的在最后）
            ticker: 股票代码（可选，用于匹配）
            message_timestamp: 消息时间戳（用于解析相对日期）
            
        Returns:
            包含期权信息的字典 {'ticker', 'option_type', 'strike', 'expiry', 'raw_message'}
        """
        # 从后往前遍历（最新的在最后）
        for msg_content in reversed(history):
            # 尝试解析
            instruction = OptionParser.parse(msg_content, message_timestamp=message_timestamp)
            
            if not instruction:
                continue
            
            # 只使用 BUY 指令作为上下文
            if instruction.instruction_type != InstructionType.BUY.value:
                continue
            
            # 如果指定了ticker，检查是否匹配
            if ticker and instruction.ticker:
                if instruction.ticker.upper() != ticker.upper():
                    continue
            
            # 确保有完整信息
            if instruction.ticker and instruction.strike:
                return {
                    'ticker': instruction.ticker,
                    'option_type': instruction.option_type,
                    'strike': instruction.strike,
                    'expiry': instruction.expiry,
                    'raw_message': msg_content
                }
        
        return None
    
    def _search_in_refer(self, refer: str, ticker: Optional[str], message_timestamp: Optional[str] = None) -> Optional[Dict]:
        """
        解析 refer 内容，提取期权信息
        
        Args:
            refer: 引用的消息内容
            ticker: 股票代码（可选，用于匹配）
            message_timestamp: 消息时间戳（用于解析相对日期）
            
        Returns:
            包含期权信息的字典
        """
        if not refer:
            return None
        
        # 直接解析 refer 内容
        instruction = OptionParser.parse(refer, message_timestamp=message_timestamp)
        
        if not instruction:
            return None
        
        # 只使用 BUY 指令作为上下文
        if instruction.instruction_type != InstructionType.BUY.value:
            return None
        
        # 如果指定了ticker，检查是否匹配
        if ticker and instruction.ticker:
            if instruction.ticker.upper() != ticker.upper():
                return None
        
        # 确保有完整信息
        if instruction.ticker and instruction.strike:
            return {
                'ticker': instruction.ticker,
                'option_type': instruction.option_type,
                'strike': instruction.strike,
                'expiry': instruction.expiry,
                'raw_message': refer
            }
        
        return None
    
    def _search_in_recent_messages(self, current_dom_id: str, ticker: Optional[str], limit: int) -> Optional[Dict]:
        """
        在当前消息之前的N条消息中查找匹配的 BUY 指令
        
        Args:
            current_dom_id: 当前消息的 domID
            ticker: 股票代码（可选，如果为None则返回最近的任意BUY指令）
            limit: 查找范围（由调用方传入，通常来自CONTEXT_SEARCH_LIMIT配置）
            
        Returns:
            包含期权信息的字典
        """
        # 获取当前消息的索引
        current_idx = self.message_index.get(current_dom_id)
        if current_idx is None:
            return None
        
        # 向前查找最多 limit 条消息
        start_idx = max(0, current_idx - limit)
        
        for idx in range(current_idx - 1, start_idx - 1, -1):
            msg = self.all_messages[idx]
            content = msg.get('content', '')
            
            # 尝试解析
            instruction = OptionParser.parse(content, message_timestamp=msg.get('timestamp'))
            
            if not instruction:
                continue
            
            # 只使用 BUY 指令
            if instruction.instruction_type != InstructionType.BUY.value:
                continue
            
            # 如果指定了ticker，检查是否匹配
            if ticker:
                if not instruction.ticker or instruction.ticker.upper() != ticker.upper():
                    continue
            
            # 确保有完整信息
            if instruction.ticker and instruction.strike:
                return {
                    'ticker': instruction.ticker,
                    'option_type': instruction.option_type,
                    'strike': instruction.strike,
                    'expiry': instruction.expiry,
                    'raw_message': content
                }
        
        return None
    
    def _apply_context(self, instruction: OptionInstruction, context: Dict) -> OptionInstruction:
        """
        将上下文信息应用到指令
        只补全缺失的字段
        
        Args:
            instruction: 原始指令
            context: 上下文信息字典
            
        Returns:
            补全后的指令
        """
        # 补全 ticker
        if not instruction.ticker and context.get('ticker'):
            instruction.ticker = context['ticker']
        
        # 补全 option_type
        if not instruction.option_type and context.get('option_type'):
            instruction.option_type = context['option_type']
        
        # 补全 strike
        if not instruction.strike and context.get('strike'):
            instruction.strike = context['strike']
        
        # 补全 expiry
        if not instruction.expiry and context.get('expiry'):
            instruction.expiry = context['expiry']
        
        return instruction
