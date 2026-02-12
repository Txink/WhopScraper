"""
期权指令正则解析器
解析各种类型的期权交易信号
"""
import re
import hashlib
from typing import Optional
from models.instruction import OptionInstruction, InstructionType

# 消息中常见非 ticker 的 2–5 字母词，不当作从正文解析的 ticker
_NON_TICKER_WORDS = frozenset({
    "CALL", "PUT", "CALLS", "PUTS", "THE", "AND", "FOR", "ALL", "OUT",
    "NEW", "ONE", "SEE", "BUY", "SELL", "ETF", "ITM", "OTM", "ATM",
})


class OptionParser:
    """期权指令解析器"""
    
    @staticmethod
    def _resolve_relative_date(relative_date: str, message_timestamp: Optional[str] = None) -> tuple:
        """
        将相对日期（如"今天"、"下周"）转换为具体日期
        
        Args:
            relative_date: 相对日期字符串
            message_timestamp: 消息时间戳（如 "Jan 22, 2026 10:41 PM"）
            
        Returns:
            (具体日期字符串, 是否使用了当前时间兜底)
        """
        from datetime import datetime, timedelta
        
        # 解析消息时间戳；无时间戳时用当前系统时间兜底（确保 NEXT WEEK 等相对日期能解析）
        used_fallback = False
        if not message_timestamp:
            msg_date = datetime.now()
            used_fallback = True
        else:
            try:
                msg_date = datetime.strptime(message_timestamp, '%b %d, %Y %I:%M %p')
            except Exception:
                try:
                    msg_date = datetime.strptime(message_timestamp[:19], '%Y-%m-%d %H:%M:%S')
                except Exception:
                    return relative_date, False
        
        # 计算相对日期
        relative_lower = relative_date.lower()
        
        if relative_lower in ['今天', 'today']:
            target_date = msg_date
        elif relative_lower in ['明天', 'tomorrow']:
            target_date = msg_date + timedelta(days=1)
        elif relative_lower in ['本周', '这周', '当周', 'this week']:
            # 本周五
            days_until_friday = (4 - msg_date.weekday()) % 7
            if days_until_friday == 0:
                days_until_friday = 7  # 如果今天是周五，指向下周五
            target_date = msg_date + timedelta(days=days_until_friday)
        elif relative_lower in ['下周', 'next week']:
            # 下周五
            days_until_friday = (4 - msg_date.weekday()) % 7
            target_date = msg_date + timedelta(days=days_until_friday + 7)
        else:
            return relative_date, False
        
        # 返回格式化的日期（如 "1/31"）
        return target_date.strftime('%-m/%-d'), used_fallback
    
    # 开仓指令正则（多种格式支持）
    # 格式1: INTC - $52 CALLS 1月30 $1.25
    # 格式2: QQQ 11/20 614c 入场价：1.1
    # 格式3: EOSE 1月9日13.5的call 0.45
    # 格式4: RIVN 16c 3/20 1.35
    # 格式5: META 900call 2.1
    
    # 模式1: 标准格式 - 股票 行权价 [ITM/OTM/ATM] CALL/PUT 到期 价格（支持价格范围）
    # 到期支持：本周/下周/这周/当周/今天、EXPIRATION 具体日期、EXPIRATION NEXT WEEK/THIS WEEK
    OPEN_PATTERN_1 = re.compile(
        r'([A-Z]{2,5})\s*[-–]?\s*\$?(\d+(?:\.\d+)?)\s*'
        r'(?:(?:ITM|OTM|ATM)\s+)?'  # 可选的 ITM/OTM/ATM 修饰（In/Out/At The Money）
        r'(CALLS?|PUTS?)\s*'
        r'(?:(本周|下周|这周|当周|今天)(?:的)?\s*|(?:EXPIRATION\s+)?(\d{1,2}/\d{1,2}|\d{1,2}月\d{1,2}日?|1月\d{1,2}|2月\d{1,2})\s*|(?:EXPIRATION\s+)?(NEXT\s+WEEK|THIS\s+WEEK)(?:到期)?\s*)?'  # 添加"的"字和"到期"支持
        r'\$?((?:\d+(?:\.\d+)?|\.\d+)(?:-(?:\d+(?:\.\d+)?|\.\d+))?)',  # 支持 .65 格式和价格范围（保持捕获组）
        re.IGNORECASE
    )
    
    # 模式2: 简化格式 - 股票 行权价c/p 到期 价格 (如: QQQ 614c 11/20 1.1)
    # 示例: TSLA 460c 1/16 小仓位日内交易 4.10
    OPEN_PATTERN_2 = re.compile(
        r'([A-Z]{2,5})\s+(?:\d{1,2}/\d{1,2}\s+)?'
        r'(\d+(?:\.\d+)?)[cCpP]\s+'
        r'(?:(\d{1,2}/\d{1,2}|1月\d{1,2}|2月\d{1,2}|本周|下周|这周)\s+)?'
        r'(?:入场价?[：:])?\s*'
        r'(?:彩票)?\s*'  # 可选的"彩票"关键词
        r'.*?'  # 允许任意文字（非贪婪）
        r'(\d+(?:\.\d+)?|\.\d+)'  # 支持 .65 格式
        r'(?![\/])',  # 负向前瞻：确保价格后面不是 "/"（避免把日期的一部分当成价格）
        re.IGNORECASE
    )
    
    # 模式3: 到期在前格式 - 股票 到期 行权价 call/put 价格 (如: EOSE 1月9日 13.5的call 0.45)
    OPEN_PATTERN_3 = re.compile(
        r'([A-Z]{2,5})\s+'
        r'(\d{1,2}月\d{1,2}日?|本周|下周|这周)\s*'
        r'(\d+(?:\.\d+)?)(?:的)?\s*'
        r'(call|put)s?\s+'
        r'(\d+(?:\.\d+)?|\.\d+)',  # 支持 .65 格式
        re.IGNORECASE
    )
    
    # 模式4: 紧凑格式 - 股票 行权价call/put 价格 (如: META 900call 2.1)
    OPEN_PATTERN_4 = re.compile(
        r'([A-Z]{2,5})\s+'
        r'(\d+(?:\.\d+)?)(call|put)s?\s*'
        r'(?:可以)?(?:在)?'
        r'(\d+(?:\.\d+)?|\.\d+)',  # 支持 .65 格式
        re.IGNORECASE
    )
    
    # 模式5: 带$符号开头 - $RIVN 1月9日 $20 call $0.35 或 $EOSE call 本周 $18 0.5
    # 示例: $XOM 1/16 $127 call 0.8-0.85
    OPEN_PATTERN_5 = re.compile(
        r'\$([A-Z]{2,5})\s+'
        r'(?:(\d{1,2}/\d{1,2}|\d{1,2}月\d{1,2}日?)\s+)?'  # 日期可选，在前面（M/D或中文格式）
        r'(?:(call|put)s?\s+)?'  # call/put可以在前面
        r'(?:(本周|下周|这周|当周|今天)(?:的)?\s*)?'  # 支持相对日期，添加"的"字
        r'\$?(\d+(?:\.\d+)?)\s+'  # 行权价
        r'(?:(call|put)s?\s+)?'  # call/put也可以在后面
        r'\$?((?:\d+(?:\.\d+)?|\.\d+)(?:-(?:\d+(?:\.\d+)?|\.\d+))?)',  # 支持 .65 格式和价格范围
        re.IGNORECASE
    )
    
    # 模式6: 日期格式YYMMDD - rklb 251017 本周的 71call 0.6
    OPEN_PATTERN_6 = re.compile(
        r'([a-zA-Z]{2,5})\s+'
        r'\d{6}\s+'
        r'(本周|下周|这周)(?:的)?\s+'
        r'(\d+(?:\.\d+)?)(call|put)s?\s+'
        r'(?:可以注意)?.*?'
        r'(\d+(?:\.\d+)?|\.\d+)',  # 支持 .65 格式
        re.IGNORECASE
    )
    
    # 模式7: 日期在中间格式 - ticker + 日期 + strike + c/p + 价格
    # 示例: QQQ 11/20 614c 入场价：1.1 备注：小仓位
    # 示例: QQQ 12/02 623C 入场价：1.1
    OPEN_PATTERN_7 = re.compile(
        r'([A-Z]{2,5})\s+'  # ticker
        r'(\d{1,2}/\d{1,2}|\d{1,2}月\d{1,2}日?)\s+'  # 日期（必需）
        r'(\d+(?:\.\d+)?)\s*'  # 行权价
        r'[cCpP](?:all|ut)?s?\s*'  # c/p/call/put
        r'(?:入场价?[：:])?\s*'
        r'(?:备注[：:]?)?\s*'
        r'((?:\d+(?:\.\d+)?|\.\d+)(?:-(?:\d+(?:\.\d+)?|\.\d+))?)',  # 价格或价格区间
        re.IGNORECASE
    )
    
    # 模式8: 中文期权类型支持 - 支持"看涨期权"/"看跌期权"
    # 示例: $QQQ 12月17日 608看涨期权 入场： 0.7
    # 示例: MCD - 下周到期 $327.5 看涨期权 $2.75
    OPEN_PATTERN_8 = re.compile(
        r'\$?([A-Z]{2,5})\s*[-–]?\s*'
        r'(?:(下周|本周|这周)(?:到期)?)??\s*'  # 可选的相对日期
        r'(?:(\d{1,2}月\d{1,2}日?)\s+)?'  # 可选的具体日期
        r'\$?(\d+(?:\.\d+)?)\s*'  # 行权价
        r'(看涨期权|看跌期权|CALLS?|PUTS?)\s*'  # 中文或英文
        r'(?:入场[：:]?)?\s*'
        r'\$?((?:\d+(?:\.\d+)?|\.\d+)(?:-(?:\d+(?:\.\d+)?|\.\d+))?)',  # 价格
        re.IGNORECASE
    )
    
    # 止损指令正则
    # 示例: 止损 0.95
    # 示例: 止损在1.00
    # 示例: 止损价1.65美元 小仓位
    # 示例: 止损设置在0.17
    # 示例: 止损 在 1.3
    # 示例: SL 0.95
    STOP_LOSS_PATTERN = re.compile(
        r'(?:止损|SL|stop\s*loss)(?:价)?\s*(?:设置)?(?:在)?\s*(\d+(?:\.\d+)?)',
        re.IGNORECASE
    )
    
    # 反向止损正则（价格在前）
    # 示例: 2.5止损
    # 示例: 3.0止损剩下的ba
    REVERSE_STOP_LOSS_PATTERN = re.compile(
        r'(\d+(?:\.\d+)?)\s*(?:止损|SL)',
        re.IGNORECASE
    )
    
    # 调整止损正则
    # 示例: 止损提高到1.5
    # 示例: 止损调整到 1.5
    # 示例: 止损设置上移到2.16
    # 示例: 止损上移到2.25
    ADJUST_STOP_PATTERN = re.compile(
        r'(?:止损|SL|stop\s*loss)\s*(?:设置)?(?:提高|调整|移动|上调|上移)(?:到|至)?\s*(\d+(?:\.\d+)?)',
        re.IGNORECASE
    )
    
    # 止盈/出货指令正则（多种格式）
    # 示例: 1.75出三分之一
    # 示例: 1.65附近出剩下三分之二
    # 示例: 2.0 出一半
    # 示例: 0.9剩下都出
    # 示例: 1.5附近把剩下都出了
    # 示例: 0.61出剩余的
    # 示例: 4.75 amd全出
    # 示例: 2.3附近都出
    # 示例: 2.45也在剩下减一半
    
    # 价格小数点点位（支持全角。、．，逗号，如 1。63、1,5）
    _DECIMAL = r'[\.．。,]'
    # 模式1: 价格+出+比例（可选股票代码）
    TAKE_PROFIT_PATTERN_1 = re.compile(
        r'(\d+(?:' + _DECIMAL + r'\d+)?)\s*(?:附近|左右)?\s*(?:也)?'
        r'(?:出|减)\s*'
        r'(?:剩下|剩余|个)?\s*'
        r'(四分之一|三分之一|三分之二|三之一|一半|全部|1/4|1/3|2/3|1/2|\d+%)'
        r'(?:\s*([A-Z]{2,5}))?',  # 可选的股票代码
        re.IGNORECASE
    )
    
    # 模式1b: 价格或区间+开始+减/出+比例（如: 1.2-1.3开始减三分之一，区间时仅存 price_range，中间值在 resolver 填）
    TAKE_PROFIT_PATTERN_1B = re.compile(
        r'(\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)?)\s*开始\s*(?:出|减)\s*'
        r'(四分之一|三分之一|三分之二|三之一|一半|全部|1/4|1/3|2/3|1/2|\d+%)'
        r'(?:\s*([A-Z]{2,5}))?',
        re.IGNORECASE
    )
    
    # 模式2: 价格+剩下+都出 (如: 0.9剩下都出, 1,5都出剩下的)
    TAKE_PROFIT_PATTERN_2 = re.compile(
        r'(\d+(?:' + _DECIMAL + r'\d+)?)\s*(?:附近|左右)?\s*'
        r'(?:把)?(?:剩下|剩余)(?:的)?(?:都|全)?出(?:了)?',
        re.IGNORECASE
    )
    
    # 模式3: 价格+出(掉)?+剩余/剩下的+可选ticker → CLOSE (如: 0.61出剩余的, 0.94出掉剩下的cmcsa期权)
    TAKE_PROFIT_PATTERN_3 = re.compile(
        r'(\d+(?:\.\d+)?)\s*(?:附近)?\s*出(?:掉)?\s*(?:剩余|剩下)(?:的)?\s*([A-Za-z]{2,5})?',
        re.IGNORECASE
    )
    
    # 模式4: 价格+出+可选ticker+彩票+全出 (如: 4.75 amd全出, 1.7出 cop彩票全出)
    TAKE_PROFIT_PATTERN_4 = re.compile(
        r'(\d+(?:\.\d+)?)\s*(?:出)?\s*([A-Z]{2,5})?\s*(?:彩票)?\s*全出',
        re.IGNORECASE
    )
    
    # 模式5: 价格+附近+都出 (如: 2.3附近都出)
    TAKE_PROFIT_PATTERN_5 = re.compile(
        r'(\d+(?:\.\d+)?)\s*附近\s*都出',
        re.IGNORECASE
    )
    
    # 模式5d: 价格+附近+也?可以?分批?都出+可选ticker (如: 1.5附近也可以分批都出qqq掉下来了)
    TAKE_PROFIT_PATTERN_5D = re.compile(
        r'(\d+(?:\.\d+)?)\s*附近\s*(?:也)?(?:可以)?(?:分批)?\s*都出\s*([A-Za-z]{2,5})?',
        re.IGNORECASE
    )
    
    # 模式2b: 剩下也(在)?+价格+附近?+出 (如: 剩下也1.25附近出, 剩下也在1.45出) → CLOSE
    TAKE_PROFIT_PATTERN_2B = re.compile(
        r'(?:剩下|剩余)(?:也)?(?:在)?\s*(\d+(?:\.\d+)?)\s*(?:附近|左右)?\s*(?:出|减)',
        re.IGNORECASE
    )
    
    # 模式5c: 价格+附近+也+减点/出点 → SELL，默认数量 1/3（无 ticker 需上下文补全）
    # 示例: 1.4附近也减点, 2.0附近出点（都出/全出 见模式5、5b → CLOSE）
    TAKE_PROFIT_PATTERN_5C = re.compile(
        r'^(\d+(?:\.\d+)?)\s*(?:附近|左右)?\s*(?:也)?\s*(?:出|减)(?:点|了)?\s*$',
        re.IGNORECASE
    )
    # 模式5i: 价格+也减点（后可有其他字，无 ticker 由历史补全）→ SELL 1/3（如: 3.4也减点 剩下拿一半）
    TAKE_PROFIT_PATTERN_5I = re.compile(
        r'(\d+(?:\.\d+)?)\s*(?:附近|左右)?\s*也减点',
        re.IGNORECASE
    )
    # 模式5e: 价格+附近+出（未说“出点”“出一点”）→ CLOSE（如: 1.15附近出走弱了）
    TAKE_PROFIT_PATTERN_5E = re.compile(
        r'(\d+(?:\.\d+)?)\s*附近\s*出',
        re.IGNORECASE
    )
    # 模式5f: 价格+出了（未说数量/比例）→ CLOSE（如: 机器是1.7出了等下一个慢速点的）
    TAKE_PROFIT_PATTERN_5F = re.compile(
        r'(\d+(?:\.\d+)?)\s*出了',
        re.IGNORECASE
    )
    # 模式5g: ticker+价格+也减点（无具体数量当 1/3）（如: eose 0.57也减点 持仓原来的一半 博价内）
    TAKE_PROFIT_PATTERN_5G = re.compile(
        r'([A-Za-z]{2,5})\s+(\d+(?:\.\d+)?)\s*也减点',
        re.IGNORECASE
    )
    # 模式5h: 价格+在减点+ticker（无具体数量当 1/3）（如: 4.6在减点tsla 留4分之一原来仓位）
    TAKE_PROFIT_PATTERN_5H = re.compile(
        r'(\d+(?:\.\d+)?)\s*在减点\s*([A-Za-z]{2,5})',
        re.IGNORECASE
    )
    
    # 模式5b: 价格+都出/全出/全部出+可选ticker (如: 2.75都出 hon, 2.3全出, 1,5都出剩下的)
    TAKE_PROFIT_PATTERN_5B = re.compile(
        r'(\d+(?:' + _DECIMAL + r'\d+)?)\s*(?:都|全部|全)出\s*([A-Z]{2,5})?',
        re.IGNORECASE
    )
    
    # 模式6: 价格+再出+比例 (如: 0.7再出剩下的一半)
    TAKE_PROFIT_PATTERN_6 = re.compile(
        r'(\d+(?:\.\d+)?)\s*(?:再|也)?(?:在)?\s*(?:剩下)?\s*(?:出|减)\s*(?:剩下|剩余)?\s*(一半|三分之一|三分之二)',
        re.IGNORECASE
    )
    
    # 模式7: 行权价描述+到价格出 (如: 47 call到1.1出)
    TAKE_PROFIT_PATTERN_7 = re.compile(
        r'\d+\s*(?:call|put)\s*到\s*(\d+(?:\.\d+)?)\s*出',
        re.IGNORECASE
    )
    
    # 模式8: 价格+也在剩下减一半 (如: 2.45也在剩下减一半)
    TAKE_PROFIT_PATTERN_8 = re.compile(
        r'(\d+(?:\.\d+)?)\s*也在?\s*剩下\s*减\s*(一半|三分之一|三分之二)',
        re.IGNORECASE
    )
    
    # 模式9: ticker+跳到价格+都出 (如: ndaq又跳到2.7的 也是刚才没出的都出)
    TAKE_PROFIT_PATTERN_9 = re.compile(
        r'([A-Z]{2,5})\s*(?:又)?(?:跳到|到了?)\s*(\d+(?:\.\d+)?)(?:的)?\s*.*?(?:都|全)?出',
        re.IGNORECASE
    )
    
    # 模式10: ticker+价格+都出/出剩下的 (如: unp 2.35都出剩下的, ndaq 2.4都出)
    TAKE_PROFIT_PATTERN_10 = re.compile(
        r'([A-Z]{2,5})\s+(\d+(?:\.\d+)?)\s*(?:(?:都|全)?出(?:剩下|剩余)(?:的)?|(?:都|全)出)',
        re.IGNORECASE
    )
    
    # 模式11: ticker+卖出/出+比例 (如: tsla 卖出 1/3, nvda 出一半, amd 卖出30%)
    TAKE_PROFIT_PATTERN_11 = re.compile(
        r'([A-Z]{2,5})\s+(?:卖出|出)\s*(四分之一|三分之一|三分之二|一半|全部|1/4|1/3|2/3|1/2|\d+%)',
        re.IGNORECASE
    )
    
    # 模式12: ticker+价格+卖出/出+比例 (如: tsla 0.17 卖出 1/3, nvda 1.5 出一半)
    TAKE_PROFIT_PATTERN_12 = re.compile(
        r'([A-Z]{2,5})\s+(\d+(?:\.\d+)?)\s+(?:卖出|出)\s*(四分之一|三分之一|三分之二|一半|全部|1/4|1/3|2/3|1/2|\d+%)',
        re.IGNORECASE
    )
    # 模式12b: 价格+可以出+剩下比例+的+ticker (如: 4.3可以出剩下四分之一的pltr)
    TAKE_PROFIT_PATTERN_12B = re.compile(
        r'(\d+(?:\.\d+)?)\s*可以出\s*剩下\s*(四分之一|三分之一|三分之二|一半|全部|1/4|1/3|2/3|1/2|\d+%)\s*的?\s*([A-Za-z]{2,5})',
        re.IGNORECASE
    )
    
    # 模式13: 价格+出/减+ticker+strike+call/put - 带详细期权信息的卖出
    # 示例: 0.47 出rivn 19.5 call
    # 示例: 0.4也减点 rivn 20call
    # 示例: 1.65附近 46 call 剩余都出了
    # 示例: 4.15-4.2出 amzn亚马逊call 有点慢
    TAKE_PROFIT_PATTERN_13 = re.compile(
        r'((?:\d+(?:\.\d+)?|\.\d+)(?:-(?:\d+(?:\.\d+)?|\.\d+))?)\s*'  # 价格或价格区间
        r'(?:附近)?\s*'
        r'(?:也)?(?:出|减)(?:点|了)?\s*'
        r'(?:[A-Za-z\u4e00-\u9fa5]+\s+)?'  # 可选的中文/英文描述词（如"亚马逊"）
        r'([A-Z]{2,5})\s*'  # ticker（可能紧跟在中文后）
        r'(\d+(?:\.\d+)?)\s*'  # strike
        r'(call|put)s?',  # option type
        re.IGNORECASE
    )
    
    # 模式13的简化版: 价格区间+出+中文+ticker+call/put（不含strike）
    # 示例: 4.15-4.2出 amzn亚马逊call（支持小写ticker）
    TAKE_PROFIT_PATTERN_13B = re.compile(
        r'((?:\d+(?:\.\d+)?|\.\d+)(?:-(?:\d+(?:\.\d+)?|\.\d+))?)\s*'  # 价格或价格区间
        r'(?:附近)?\s*'
        r'(?:也)?(?:出|减)(?:点|了)?\s*'
        r'([a-z]{2,5})[\u4e00-\u9fa5]*\s*'  # 小写ticker + 可选中文描述（如 amzn亚马逊）
        r'(call|put)s?',  # option type（不含strike）
        re.IGNORECASE
    )
    
    # 模式14: ticker+在+价格+减仓+比例
    # 示例: TSLA 在 4.40 减仓一半
    TAKE_PROFIT_PATTERN_14 = re.compile(
        r'([A-Z]{2,5})\s+在\s+(\d+(?:\.\d+)?)\s+减仓\s*(三分之一|三分之二|一半|全部|1/3|2/3|1/2|\d+%)',
        re.IGNORECASE
    )
    
    # 模式15: 价格+止盈+比例+ticker
    # 示例: 1.5止盈一半intc
    TAKE_PROFIT_PATTERN_15 = re.compile(
        r'(\d+(?:\.\d+)?)\s*止盈\s*(三分之一|三分之二|一半|全部|1/3|2/3|1/2|\d+%)?\s*([A-Z]{2,5})?',
        re.IGNORECASE
    )
    
    # 模式16: ticker+剩下部分+也+价格+附近出
    # 示例: nvda剩下部分也2.45附近出
    TAKE_PROFIT_PATTERN_16 = re.compile(
        r'([A-Z]{2,5})\s*(?:剩下|剩余)(?:部分|的)?(?:也)?\s*(\d+(?:\.\d+)?)\s*(?:附近)?(?:出|减)',
        re.IGNORECASE
    )
    
    # 模式17: ticker+strike+call/put+...+剩下+价格+出
    # 示例: iren 46 call 快进入46价内了 可以剩下的1.6-1.7分批出（支持小写ticker和价格中的中文句号）
    TAKE_PROFIT_PATTERN_17 = re.compile(
        r'([a-zA-Z]{2,5})\s+'  # ticker（支持大小写）
        r'(\d+(?:\.\d+)?)\s+'  # strike
        r'(call|put)s?\s+'  # option type
        r'.*?'  # 任意中间文字（非贪婪）
        r'(?:剩下|剩余)(?:的)?\s*'  # 关键词"剩下"或"剩余"，"的"可选
        r'([\d\.。]+(?:-[\d\.。]+)?)\s*'  # 价格或价格区间（支持中文句号作为小数点）
        r'(?:附近)?(?:分批)?(?:出|减)',
        re.IGNORECASE
    )
    
    # 仓位大小正则
    # 示例: 小仓位
    # 示例: 中仓位
    # 示例: 大仓位
    POSITION_SIZE_PATTERN = re.compile(
        r'(小仓位|中仓位|大仓位|轻仓|重仓|半仓|满仓)',
        re.IGNORECASE
    )
    
    # 比例映射
    PORTION_MAP = {
        '三分之一': '1/3',
        '三之一': '1/3',  # 错别字
        '三分之二': '2/3',
        '一半': '1/2',
        '全部': '全部',
        '1/3': '1/3',
        '2/3': '2/3',
        '1/2': '1/2',
    }
    
    @classmethod
    def parse(cls, message: str, message_id: Optional[str] = None, message_timestamp: Optional[str] = None) -> Optional[OptionInstruction]:
        """
        解析消息文本，返回期权指令
        
        Args:
            message: 原始消息文本
            message_id: 消息唯一标识（用于去重）
            message_timestamp: 消息发送时间（用于计算相对日期，如"今天"、"下周"）
            
        Returns:
            OptionInstruction 或 None（如果无法解析）
        """
        message = message.strip()
        if not message:
            return None
        
        # 归一化带点的 ticker（如 BRK.B → BRKB, BF.A → BFA）
        message = cls._normalize_dot_tickers(message)
        
        # 生成消息 ID（如果未提供）
        if not message_id:
            message_id = hashlib.md5(message.encode()).hexdigest()[:12]
        
        # 优先尝试解析买入指令（传入时间戳用于计算相对日期）
        instruction = cls._parse_buy(message, message_id, message_timestamp)
        if instruction:
            # 标记：消息无时间戳且到期日是从相对日期解析而来（使用了当前时间兜底）
            if not message_timestamp and instruction.expiry:
                _RELATIVE_DATE_KEYWORDS = {'今天', '明天', 'today', 'tomorrow', '本周', '这周', '当周', '下周',
                                           'this week', 'next week', 'expiration next week', 'expiration this week'}
                msg_lower = message.lower()
                if any(kw in msg_lower for kw in _RELATIVE_DATE_KEYWORDS):
                    instruction.expiry_fallback_time = True
            cls._fill_ticker_from_message_if_missing(instruction, message)
            return instruction
        
        # 尝试解析修改指令（止损/止盈）
        instruction = cls._parse_modify(message, message_id)
        if instruction:
            cls._fill_ticker_from_message_if_missing(instruction, message)
            return instruction
        
        # 尝试解析卖出/清仓指令
        instruction = cls._parse_sell(message, message_id)
        if instruction:
            cls._fill_ticker_from_message_if_missing(instruction, message)
            return instruction
        
        # 无法解析
        return None
    
    # 带点的 ticker 归一化正则：匹配 BRK.B、BF.A 等（2-4字母 + 点 + 1字母）
    _DOT_TICKER_RE = re.compile(r'(?<![A-Za-z])([A-Za-z]{2,4})\.([A-Za-z])(?![A-Za-z])')

    @classmethod
    def _normalize_dot_tickers(cls, message: str) -> str:
        """将带点的 ticker（如 BRK.B → BRKB）归一化，避免正则无法匹配。"""
        return cls._DOT_TICKER_RE.sub(r'\1\2', message)

    @classmethod
    def _fill_ticker_from_message_if_missing(cls, instruction: OptionInstruction, message: str) -> None:
        """当指令无 ticker 时，从消息正文解析首个 ticker 并填入，便于 resolver 从历史匹配同标的。"""
        if instruction.ticker:
            return
        ticker = cls._extract_ticker_from_message(message)
        if ticker:
            instruction.ticker = ticker

    @staticmethod
    def _extract_ticker_from_message(message: str) -> Optional[str]:
        """
        从消息正文解析首个可能的 ticker（2–5 字母，排除常见非 ticker）。
        不用 \\b：Python 中 \\w 含 Unicode 字母，ticker 后紧跟中文（如「tsla剩下」）时无 word boundary，
        改为要求 ticker 两侧为非字母或首/尾。
        """
        if not message or len(message.strip()) < 2:
            return None
        words = re.findall(r"(?:^|[^A-Za-z])([A-Za-z]{2,5})(?=[^A-Za-z]|$)", message)
        for w in words:
            u = w.upper()
            if u not in _NON_TICKER_WORDS:
                return u
        return None

    @staticmethod
    def _parse_price_range(price_str: str) -> tuple:
        """
        解析价格字符串，返回 (单价, 价格区间)
        支持全角句号。、全角点．作为小数点（如 1。63 → 1.63）；
        支持逗号作为小数点（如 1,5 → 1.5）。
        
        Args:
            price_str: 价格字符串，如 "0.83"、"1。63"、"1,5" 或 "0.83-0.85"
            
        Returns:
            (price, price_range): 单价和价格区间
            - 如果是单价：返回 (0.83, None)
            - 如果是区间：返回 (None, [0.83, 0.85])，中间值由 resolver 填
        """
        if not price_str or not str(price_str).strip():
            return (None, None)
        s = str(price_str).strip()
        s = s.replace("。", ".").replace("．", ".")
        # 兼容逗号作小数点（如 1,5 → 1.5）：仅当逗号后为 1～3 位数字时替换
        s = re.sub(r"(\d),(\d{1,3})\b", r"\1.\2", s)
        if "-" in s:
            try:
                parts = s.split("-", 1)
                price_low = float(parts[0].strip())
                price_high = float(parts[1].strip())
                return (None, [price_low, price_high])
            except Exception:
                try:
                    return (float(parts[0].strip()), None)
                except Exception:
                    return (None, None)
        try:
            return (float(s), None)
        except Exception:
            return (None, None)
    
    @classmethod
    def _parse_buy(cls, message: str, message_id: str, message_timestamp: Optional[str] = None) -> Optional[OptionInstruction]:
        """解析买入指令 - 尝试多种模式（按优先级顺序）"""
        
        # 优先尝试模式7: 日期在中间格式 (QQQ 11/20 614c 1.1) - 最具体，包含完整信息
        match = cls.OPEN_PATTERN_7.search(message)
        if match:
            ticker = match.group(1).upper()
            expiry_raw = match.group(2)
            strike = float(match.group(3))
            price_str = match.group(4)
            
            # 从消息中判断期权类型（c/p/call/put）
            option_type_match = re.search(r'(\d+(?:\.\d+)?)\s*[cCpP](?:all|ut)?', message)
            if option_type_match:
                option_char = message[option_type_match.end(1):option_type_match.end(1)+1].upper()
                option_type = 'CALL' if option_char == 'C' else 'PUT'
            else:
                option_type = 'CALL'  # 默认
            
            # 解析价格（支持价格区间）
            price, price_range = cls._parse_price_range(price_str)
            
            # 处理日期（直接使用，不需要 resolve 因为已经是 M/D 格式）
            expiry = expiry_raw if expiry_raw else None
            
            position_match = cls.POSITION_SIZE_PATTERN.search(message)
            position_size = position_match.group(1) if position_match else None
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                option_type=option_type,
                strike=strike,
                expiry=expiry,
                price=price,
                price_range=price_range,
                position_size=position_size,
                message_id=message_id
            )
        
        # 尝试模式1: 标准格式
        match = cls.OPEN_PATTERN_1.search(message)
        if match:
            ticker = match.group(1).upper()
            strike = float(match.group(2))
            option_type = match.group(3).upper()
            option_type = 'CALL' if option_type.startswith('CALL') else 'PUT'
            # group(4) 相对日期中文，group(5) 具体日期，group(6) EXPIRATION NEXT/THIS WEEK
            expiry_raw = match.group(4) or match.group(5) or match.group(6)
            price_str = match.group(7)
            
            # 解析价格（支持价格区间）
            price, price_range = cls._parse_price_range(price_str)
            
            # 处理相对日期
            (expiry, _expiry_fallback) = cls._resolve_relative_date(expiry_raw, message_timestamp) if expiry_raw else (None, False)
            
            position_match = cls.POSITION_SIZE_PATTERN.search(message)
            position_size = position_match.group(1) if position_match else None
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                option_type=option_type,
                strike=strike,
                expiry=expiry,
                price=price,
                price_range=price_range,
                position_size=position_size,
                message_id=message_id
            )
        
        # 尝试模式2: 简化格式 (614c)
        match = cls.OPEN_PATTERN_2.search(message)
        if match:
            ticker = match.group(1).upper()
            strike = float(match.group(2))
            # 从614c中提取c或p
            option_indicator = message[match.start():match.end()]
            option_type = 'CALL' if 'c' in option_indicator or 'C' in option_indicator else 'PUT'
            expiry_raw = match.group(3) if match.group(3) else None
            price_str = match.group(4)
            
            # 解析价格（支持价格区间）
            price, price_range = cls._parse_price_range(price_str)
            
            # 处理相对日期
            (expiry, _expiry_fallback) = cls._resolve_relative_date(expiry_raw, message_timestamp) if expiry_raw else (None, False)
            
            position_match = cls.POSITION_SIZE_PATTERN.search(message)
            position_size = position_match.group(1) if position_match else None
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                option_type=option_type,
                strike=strike,
                expiry=expiry,
                price=price,
                price_range=price_range,
                position_size=position_size,
                message_id=message_id
            )
        
        # 尝试模式3: 到期在前格式
        match = cls.OPEN_PATTERN_3.search(message)
        if match:
            ticker = match.group(1).upper()
            expiry_raw = match.group(2)
            strike = float(match.group(3))
            option_type = match.group(4).upper()
            option_type = 'CALL' if option_type.startswith('CALL') else 'PUT'
            price_str = match.group(5)
            
            # 解析价格（支持价格区间）
            price, price_range = cls._parse_price_range(price_str)
            
            # 处理相对日期
            (expiry, _expiry_fallback) = cls._resolve_relative_date(expiry_raw, message_timestamp) if expiry_raw else (None, False)
            
            position_match = cls.POSITION_SIZE_PATTERN.search(message)
            position_size = position_match.group(1) if position_match else None
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                option_type=option_type,
                strike=strike,
                expiry=expiry,
                price=price,
                price_range=price_range,
                position_size=position_size,
                message_id=message_id
            )
        
        # 尝试模式4: 紧凑格式 (900call)
        match = cls.OPEN_PATTERN_4.search(message)
        if match:
            ticker = match.group(1).upper()
            strike = float(match.group(2))
            option_type = match.group(3).upper()
            option_type = 'CALL' if option_type.startswith('CALL') else 'PUT'
            price_str = match.group(4)
            
            # 解析价格（支持价格区间）
            price, price_range = cls._parse_price_range(price_str)
            
            position_match = cls.POSITION_SIZE_PATTERN.search(message)
            position_size = position_match.group(1) if position_match else None
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                option_type=option_type,
                strike=strike,
                expiry=None,
                price=price,
                price_range=price_range,
                position_size=position_size,
                message_id=message_id
            )
        
        # 尝试模式5: 带$符号开头（$EOSE call 本周 $18 0.5）
        # 分组: 1=ticker, 2=具体日期, 3=call/put在前, 4=相对日期, 5=strike, 6=call/put在后, 7=price
        match = cls.OPEN_PATTERN_5.search(message)
        if match:
            ticker = match.group(1).upper()
            # call/put可能在group 3或group 6 (修复：之前错误地使用了group 2)
            option_type_str = match.group(3) or match.group(6)
            if option_type_str:
                option_type = 'CALL' if option_type_str.upper().startswith('CALL') else 'PUT'
            else:
                option_type = 'CALL'  # 默认CALL
            
            # 获取日期 (修复：之前分组索引错误)
            specific_date = match.group(2)  # 1月9日 或 1/16
            relative_date = match.group(4)  # 本周、下周
            expiry_raw = specific_date or relative_date
            
            strike = float(match.group(5))
            price_str = match.group(7)
            
            # 解析价格（支持价格区间）
            price, price_range = cls._parse_price_range(price_str)
            
            # 处理日期
            (expiry, _expiry_fallback) = cls._resolve_relative_date(expiry_raw, message_timestamp) if expiry_raw else (None, False)
            
            position_match = cls.POSITION_SIZE_PATTERN.search(message)
            position_size = position_match.group(1) if position_match else None
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                option_type=option_type,
                strike=strike,
                expiry=expiry,
                price=price,
                price_range=price_range,
                position_size=position_size,
                message_id=message_id
            )
        
        # 尝试模式6: 日期格式YYMMDD
        match = cls.OPEN_PATTERN_6.search(message)
        if match:
            ticker = match.group(1).upper()
            expiry_raw = match.group(2)
            strike = float(match.group(3))
            option_type = match.group(4).upper()
            option_type = 'CALL' if option_type.startswith('CALL') else 'PUT'
            price_str = match.group(5)
            
            # 解析价格（支持价格区间）
            price, price_range = cls._parse_price_range(price_str)
            
            # 处理相对日期
            (expiry, _expiry_fallback) = cls._resolve_relative_date(expiry_raw, message_timestamp) if expiry_raw else (None, False)
            
            position_match = cls.POSITION_SIZE_PATTERN.search(message)
            position_size = position_match.group(1) if position_match else None
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                option_type=option_type,
                strike=strike,
                expiry=expiry,
                price=price,
                price_range=price_range,
                position_size=position_size,
                message_id=message_id
            )
        
        # 尝试模式8: 中文期权类型 ($QQQ 12月17日 608看涨期权 0.7)
        match = cls.OPEN_PATTERN_8.search(message)
        if match:
            ticker = match.group(1).upper()
            relative_date = match.group(2)  # 下周/本周
            specific_date = match.group(3)  # 12月17日
            strike = float(match.group(4))
            option_type_str = match.group(5)
            price_str = match.group(6)
            
            # 解析期权类型
            if '看涨' in option_type_str or 'CALL' in option_type_str.upper():
                option_type = 'CALL'
            else:
                option_type = 'PUT'
            
            # 解析价格（支持价格区间）
            price, price_range = cls._parse_price_range(price_str)
            
            # 处理日期
            expiry_raw = relative_date or specific_date
            (expiry, _expiry_fallback) = cls._resolve_relative_date(expiry_raw, message_timestamp) if expiry_raw else (None, False)
            
            position_match = cls.POSITION_SIZE_PATTERN.search(message)
            position_size = position_match.group(1) if position_match else None
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                option_type=option_type,
                strike=strike,
                expiry=expiry,
                price=price,
                price_range=price_range,
                position_size=position_size,
                message_id=message_id
            )
        
        return None
    
    @classmethod
    def _parse_modify(cls, message: str, message_id: str) -> Optional[OptionInstruction]:
        """
        解析修改指令（止损/止盈）
        
        支持格式：
        - 止损 0.95
        - 止损提高到1.5
        - 止损提高到3.2 tsla期权今天也是日内的
        """
        # 尝试提取消息中的股票代码（支持大小写）
        ticker = None
        # 优先匹配"XXX期权/期货/股票"格式
        ticker_match = re.search(r'([A-Za-z]{2,5})(?:期权|期货|股票)', message)
        if not ticker_match:
            # 尝试匹配"的XXX"或"剩下的XXX"格式
            ticker_match = re.search(r'(?:剩下)?的\s*([A-Za-z]{2,5})(?:\s|$)', message)
        if not ticker_match:
            # 尝试匹配独立的大写股票代码
            ticker_match = re.search(r'\b([A-Z]{2,5})\b', message)
        
        if ticker_match:
            potential_ticker = ticker_match.group(1).upper()
            # 过滤掉一些常见的非股票代码词汇
            if potential_ticker not in ['SL', 'TP', 'STOP', 'LOSS', 'TAKE', 'PROFIT']:
                ticker = potential_ticker
        
        # 尝试匹配调整止损（优先级高）
        adjust_match = cls.ADJUST_STOP_PATTERN.search(message)
        if adjust_match:
            price_str = adjust_match.group(1)
            price, price_range = cls._parse_price_range(price_str)
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.MODIFY.value,
                ticker=ticker,
                stop_loss_price=price,
                stop_loss_range=price_range,
                message_id=message_id
            )
        
        # 尝试匹配普通止损
        stop_loss_match = cls.STOP_LOSS_PATTERN.search(message)
        if stop_loss_match:
            price_str = stop_loss_match.group(1)
            price, price_range = cls._parse_price_range(price_str)
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.MODIFY.value,
                ticker=ticker,
                stop_loss_price=price,
                stop_loss_range=price_range,
                message_id=message_id
            )
        
        # 尝试匹配反向止损（价格在前）
        reverse_stop_match = cls.REVERSE_STOP_LOSS_PATTERN.search(message)
        if reverse_stop_match:
            price_str = reverse_stop_match.group(1)
            price, price_range = cls._parse_price_range(price_str)
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.MODIFY.value,
                ticker=ticker,
                stop_loss_price=price,
                stop_loss_range=price_range,
                message_id=message_id
            )
        
        return None
    
    @staticmethod
    def _parse_sell_quantity(portion_str: str) -> tuple:
        """
        解析卖出数量，返回 (instruction_type, sell_quantity)
        
        Args:
            portion_str: 数量字符串，如 "1/3", "30%", "100", "全部"
            
        Returns:
            (instruction_type, sell_quantity):
            - SELL类型: ("SELL", "1/3") 或 ("SELL", "30%") 或 ("SELL", "100")
            - CLOSE类型: ("CLOSE", None)
        """
        portion_str = portion_str.strip()
        
        # 判断是否为清仓
        if portion_str in ['全部', '剩下', '都', '剩余']:
            return (InstructionType.CLOSE.value, None)
        
        # 判断是否为百分比
        if portion_str.endswith('%'):
            return (InstructionType.SELL.value, portion_str)
        
        # 判断是否为比例（如 1/3, 2/3, 1/4）
        if '/' in portion_str or portion_str in ['三分之一', '三分之二', '一半', '四分之一']:
            # 转换中文比例
            portion_map = {
                '三分之一': '1/3',
                '三之一': '1/3',
                '三分之二': '2/3',
                '一半': '1/2',
                '四分之一': '1/4',
            }
            quantity = portion_map.get(portion_str, portion_str)
            return (InstructionType.SELL.value, quantity)
        
        # 判断是否为具体数量（纯数字）
        try:
            int(portion_str)
            return (InstructionType.SELL.value, portion_str)
        except:
            pass
        
        # 默认当作全部
        return (InstructionType.CLOSE.value, None)
    
    @classmethod
    def _parse_sell(cls, message: str, message_id: str) -> Optional[OptionInstruction]:
        """解析卖出/清仓指令 - 尝试多种模式"""
        
        # 尝试模式13: 价格+出/减+ticker+strike+call/put - 带详细期权信息
        # 示例: 0.47 出rivn 19.5 call, 1.65附近 46 call 剩余都出了
        # 注意：此模式需要最优先匹配，因为包含最详细的信息
        match = cls.TAKE_PROFIT_PATTERN_13.search(message)
        if match:
            price_str = match.group(1)
            ticker = match.group(2).upper()
            strike = float(match.group(3))
            option_type_str = match.group(4).upper()
            option_type = 'CALL' if option_type_str.startswith('CALL') else 'PUT'
            
            # 解析价格
            price, price_range = cls._parse_price_range(price_str)
            
            # 判断是否全部出
            if '都出' in message or '全出' in message or '剩余都出' in message or '剩下都出' in message:
                instruction_type = InstructionType.CLOSE.value
                sell_quantity = None
            else:
                # 尝试解析卖出比例
                portion_match = re.search(r'(三分之一|三分之二|一半|全部|1/3|2/3|1/2|\d+%)', message)
                if portion_match:
                    instruction_type, sell_quantity = cls._parse_sell_quantity(portion_match.group(1))
                else:
                    instruction_type = InstructionType.SELL.value
                    # 减点/出点 没说数量，默认 1/3
                    sell_quantity = "1/3" if ("减点" in message or "出点" in message) else None
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=instruction_type,
                ticker=ticker,
                option_type=option_type,
                strike=strike,
                price=price,
                price_range=price_range,
                sell_quantity=sell_quantity,
                message_id=message_id
            )
        
        # 尝试模式13B: 价格+出/减+ticker+call/put（不含strike）
        # 示例: 4.15-4.2出 amzn亚马逊call
        match = cls.TAKE_PROFIT_PATTERN_13B.search(message)
        if match:
            price_str = match.group(1)
            ticker = match.group(2).upper()  # 小写ticker
            option_type_str = match.group(3).upper()  # call/put
            option_type = 'CALL' if option_type_str.startswith('CALL') else 'PUT'
            
            # 解析价格
            price, price_range = cls._parse_price_range(price_str)
            
            # 判断是否全部出
            if '都出' in message or '全出' in message:
                instruction_type = InstructionType.CLOSE.value
                sell_quantity = None
            else:
                instruction_type = InstructionType.SELL.value
                # 减点/出点 没说数量，默认 1/3
                sell_quantity = "1/3" if ("减点" in message or "出点" in message) else None
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=instruction_type,
                ticker=ticker,
                option_type=option_type,
                price=price,
                price_range=price_range,
                sell_quantity=sell_quantity,
                message_id=message_id
            )
        
        # 尝试模式12: ticker+价格+卖出/出+比例（如: tsla 0.17 卖出 1/3, nvda 1.5 出一半）
        # 注意：此模式需要优先匹配，因为它更具体（包含ticker）
        match = cls.TAKE_PROFIT_PATTERN_12.search(message)
        if match:
            ticker = match.group(1).upper()
            price_str = match.group(2)
            portion_raw = match.group(3)
            
            # 解析价格
            price, price_range = cls._parse_price_range(price_str)
            
            # 解析卖出数量
            instruction_type, sell_quantity = cls._parse_sell_quantity(portion_raw)
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=instruction_type,
                ticker=ticker,
                price=price,
                price_range=price_range,
                sell_quantity=sell_quantity,
                message_id=message_id
            )
        
        # 尝试模式12b: 价格+可以出+剩下比例+的+ticker（如: 4.3可以出剩下四分之一的pltr）
        match = cls.TAKE_PROFIT_PATTERN_12B.search(message)
        if match:
            price_str = match.group(1)
            portion_raw = match.group(2)
            ticker = match.group(3).upper()
            price, price_range = cls._parse_price_range(price_str)
            instruction_type, sell_quantity = cls._parse_sell_quantity(portion_raw)
            return OptionInstruction(
                raw_message=message,
                instruction_type=instruction_type,
                ticker=ticker,
                price=price,
                price_range=price_range,
                sell_quantity=sell_quantity,
                message_id=message_id
            )
        
        # 尝试模式1b: 价格或区间+开始+减/出+比例（如: 1.2-1.3开始减三分之一）
        match = cls.TAKE_PROFIT_PATTERN_1B.search(message)
        if match:
            price_str = match.group(1)
            portion_raw = match.group(2)
            ticker = match.group(3).upper() if match.group(3) else None
            price, price_range = cls._parse_price_range(price_str)
            instruction_type, sell_quantity = cls._parse_sell_quantity(portion_raw)
            return OptionInstruction(
                raw_message=message,
                instruction_type=instruction_type,
                ticker=ticker,
                price=price,
                price_range=price_range,
                sell_quantity=sell_quantity,
                message_id=message_id
            )
        
        # 尝试模式1: 价格+出+比例（如: 1.75出三分之一，2.8出一半nvda）
        match = cls.TAKE_PROFIT_PATTERN_1.search(message)
        if match:
            price_str = match.group(1)
            portion_raw = match.group(2)
            ticker = match.group(3).upper() if match.group(3) else None  # 可选的股票代码
            
            # 解析价格
            price, price_range = cls._parse_price_range(price_str)
            
            # 解析卖出数量
            instruction_type, sell_quantity = cls._parse_sell_quantity(portion_raw)
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=instruction_type,
                ticker=ticker,
                price=price,
                price_range=price_range,
                sell_quantity=sell_quantity,
                message_id=message_id
            )
        
        # 尝试模式2: 价格+剩下都出（如: 0.9剩下都出）
        match = cls.TAKE_PROFIT_PATTERN_2.search(message)
        if match:
            price_str = match.group(1)
            price, price_range = cls._parse_price_range(price_str)
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.CLOSE.value,
                price=price,
                price_range=price_range,
                message_id=message_id
            )
        
        # 尝试模式3: 价格+出剩余的+可选ticker（如: 0.61出剩余的, 2.4出剩下ndaq）
        match = cls.TAKE_PROFIT_PATTERN_3.search(message)
        if match:
            price_str = match.group(1)
            ticker = match.group(2).upper() if match.group(2) else None
            price, price_range = cls._parse_price_range(price_str)
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.CLOSE.value,
                ticker=ticker,
                price=price,
                price_range=price_range,
                message_id=message_id
            )
        
        # 尝试模式5b: 价格+都出/全出/全部出+可选ticker（如: 2.75都出 hon, 2.3全出, 0.16全部出tsla）
        # 注意：此模式需要在模式4之前，因为它更精确
        match = cls.TAKE_PROFIT_PATTERN_5B.search(message)
        if match:
            price_str = match.group(1)
            ticker = match.group(2).upper() if match.group(2) else None
            price, price_range = cls._parse_price_range(price_str)
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.CLOSE.value,
                ticker=ticker,
                price=price,
                price_range=price_range,
                message_id=message_id
            )
        
        # 尝试模式4: 价格+出+可选ticker+彩票+全出（如: 4.75 amd全出, 1.7出 cop彩票全出）
        match = cls.TAKE_PROFIT_PATTERN_4.search(message)
        if match:
            price_str = match.group(1)
            ticker = match.group(2).upper() if match.group(2) else None
            price, price_range = cls._parse_price_range(price_str)
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.CLOSE.value,
                ticker=ticker,
                price=price,
                price_range=price_range,
                message_id=message_id
            )
        
        # 尝试模式5: 价格+附近都出（如: 2.3附近都出）
        match = cls.TAKE_PROFIT_PATTERN_5.search(message)
        if match:
            price_str = match.group(1)
            price, price_range = cls._parse_price_range(price_str)
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.CLOSE.value,
                price=price,
                price_range=price_range,
                message_id=message_id
            )
        
        # 尝试模式5d: 价格+附近+也?可以?分批?都出+可选ticker（如: 1.5附近也可以分批都出qqq掉下来了）
        match = cls.TAKE_PROFIT_PATTERN_5D.search(message)
        if match:
            price_str = match.group(1)
            ticker = match.group(2).upper() if match.group(2) else None
            price, price_range = cls._parse_price_range(price_str)
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.CLOSE.value,
                ticker=ticker,
                price=price,
                price_range=price_range,
                message_id=message_id
            )
        
        # 尝试模式2b: 剩下也+价格+附近+出（如: 剩下也1.25附近出速度有点快）
        match = cls.TAKE_PROFIT_PATTERN_2B.search(message)
        if match:
            price_str = match.group(1)
            price, price_range = cls._parse_price_range(price_str)
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.CLOSE.value,
                price=price,
                price_range=price_range,
                message_id=message_id
            )
        
        # 尝试模式5c: 价格+附近+也+减点/出点 → SELL，默认数量 1/3（如: 1.4附近也减点）
        match = cls.TAKE_PROFIT_PATTERN_5C.search(message.strip())
        if match:
            price_str = match.group(1)
            price, price_range = cls._parse_price_range(price_str)
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                price=price,
                price_range=price_range,
                sell_quantity="1/3",
                message_id=message_id
            )
        
        # 尝试模式5i: 价格+也减点（后可有字，symbol 从历史补全）→ SELL 1/3（如: 3.4也减点 剩下拿一半）
        match = cls.TAKE_PROFIT_PATTERN_5I.search(message)
        if match:
            price_str = match.group(1)
            price, price_range = cls._parse_price_range(price_str)
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                price=price,
                price_range=price_range,
                sell_quantity="1/3",
                message_id=message_id
            )
        
        # 尝试模式5g: ticker+价格+也减点（无具体数量当 1/3）（如: eose 0.57也减点 持仓原来的一半 博价内）
        match = cls.TAKE_PROFIT_PATTERN_5G.search(message)
        if match:
            ticker = match.group(1).upper()
            price_str = match.group(2)
            price, price_range = cls._parse_price_range(price_str)
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=price,
                price_range=price_range,
                sell_quantity="1/3",
                message_id=message_id
            )
        
        # 尝试模式5h: 价格+在减点+ticker（无具体数量当 1/3）（如: 4.6在减点tsla 留4分之一原来仓位）
        match = cls.TAKE_PROFIT_PATTERN_5H.search(message)
        if match:
            price_str = match.group(1)
            ticker = match.group(2).upper()
            price, price_range = cls._parse_price_range(price_str)
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=price,
                price_range=price_range,
                sell_quantity="1/3",
                message_id=message_id
            )
        
        # 尝试模式5e: 价格+附近+出（未说出点/出一点）→ CLOSE（如: 1.15附近出走弱了）
        match = cls.TAKE_PROFIT_PATTERN_5E.search(message)
        if match and "出点" not in message and "出一点" not in message:
            price_str = match.group(1)
            price, price_range = cls._parse_price_range(price_str)
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.CLOSE.value,
                price=price,
                price_range=price_range,
                message_id=message_id
            )
        
        # 尝试模式5f: 价格+出了（未说数量/比例）→ CLOSE（如: 机器是1.7出了等下一个慢速点的）
        match = cls.TAKE_PROFIT_PATTERN_5F.search(message)
        if match:
            # 若含比例/数量则交给其他模式处理，此处仅当“出了”且无数量时判为 CLOSE
            if not re.search(r'出点|出一点|三分之一|三之一|三分之二|一半|全部|1/3|2/3|1/2|\d+%', message):
                price_str = match.group(1)
                price, price_range = cls._parse_price_range(price_str)
                return OptionInstruction(
                    raw_message=message,
                    instruction_type=InstructionType.CLOSE.value,
                    price=price,
                    price_range=price_range,
                    message_id=message_id
                )
        
        # 尝试模式6: 价格+再出+比例（如: 0.7再出剩下的一半，2.45也在剩下减一半）
        match = cls.TAKE_PROFIT_PATTERN_6.search(message)
        if match:
            price_str = match.group(1)
            portion_raw = match.group(2)
            
            # 解析价格
            price, price_range = cls._parse_price_range(price_str)
            
            # 解析卖出数量
            instruction_type, sell_quantity = cls._parse_sell_quantity(portion_raw)
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=instruction_type,
                price=price,
                price_range=price_range,
                sell_quantity=sell_quantity,
                message_id=message_id
            )
        
        # 尝试模式7: 行权价描述+到价格出（如: 47 call到1.1出）
        match = cls.TAKE_PROFIT_PATTERN_7.search(message)
        if match:
            price_str = match.group(1)
            price, price_range = cls._parse_price_range(price_str)
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.CLOSE.value,
                price=price,
                price_range=price_range,
                message_id=message_id
            )
        
        # 尝试模式8: 价格+也在剩下减一半（如: 2.45也在剩下减一半）
        match = cls.TAKE_PROFIT_PATTERN_8.search(message)
        if match:
            price_str = match.group(1)
            portion_raw = match.group(2)
            
            # 解析价格
            price, price_range = cls._parse_price_range(price_str)
            
            # 解析卖出数量
            instruction_type, sell_quantity = cls._parse_sell_quantity(portion_raw)
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=instruction_type,
                price=price,
                price_range=price_range,
                sell_quantity=sell_quantity,
                message_id=message_id
            )
        
        # 尝试模式9: ticker+跳到价格+都出（如: ndaq又跳到2.7的 也是刚才没出的都出）
        match = cls.TAKE_PROFIT_PATTERN_9.search(message)
        if match:
            ticker = match.group(1).upper()
            price_str = match.group(2)
            price, price_range = cls._parse_price_range(price_str)
            
            # 判断是否为全部出（根据消息内容判断）
            if '都出' in message or '全出' in message:
                instruction_type = InstructionType.CLOSE.value
                sell_quantity = None
            else:
                instruction_type = InstructionType.SELL.value
                sell_quantity = None
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=instruction_type,
                ticker=ticker,
                price=price,
                price_range=price_range,
                sell_quantity=sell_quantity,
                message_id=message_id
            )
        
        # 尝试模式10: ticker+价格+都出/出剩下的（如: unp 2.35都出剩下的, ndaq 2.4都出）
        match = cls.TAKE_PROFIT_PATTERN_10.search(message)
        if match:
            ticker = match.group(1).upper()
            price_str = match.group(2)
            price, price_range = cls._parse_price_range(price_str)
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.CLOSE.value,
                ticker=ticker,
                price=price,
                price_range=price_range,
                sell_quantity=None,
                message_id=message_id
            )
        
        # 尝试模式11: ticker+卖出/出+比例（市价单）（如: tsla 卖出 1/3, nvda 出一半）
        match = cls.TAKE_PROFIT_PATTERN_11.search(message)
        if match:
            ticker = match.group(1).upper()
            portion_raw = match.group(2)
            
            # 解析卖出数量
            instruction_type, sell_quantity = cls._parse_sell_quantity(portion_raw)
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=instruction_type,
                ticker=ticker,
                price=None,  # 市价单，不设置价格
                sell_quantity=sell_quantity,
                message_id=message_id
            )
        
        # 尝试模式14: ticker+在+价格+减仓+比例（如: TSLA 在 4.40 减仓一半）
        match = cls.TAKE_PROFIT_PATTERN_14.search(message)
        if match:
            ticker = match.group(1).upper()
            price_str = match.group(2)
            portion_raw = match.group(3)
            
            # 解析价格
            price, price_range = cls._parse_price_range(price_str)
            
            # 解析卖出数量
            instruction_type, sell_quantity = cls._parse_sell_quantity(portion_raw)
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=instruction_type,
                ticker=ticker,
                price=price,
                price_range=price_range,
                sell_quantity=sell_quantity,
                message_id=message_id
            )
        
        # 尝试模式15: 价格+止盈+比例+ticker（如: 1.5止盈一半intc）
        match = cls.TAKE_PROFIT_PATTERN_15.search(message)
        if match:
            price_str = match.group(1)
            portion_raw = match.group(2)
            ticker = match.group(3).upper() if match.group(3) else None
            
            # 解析价格
            price, price_range = cls._parse_price_range(price_str)
            
            # 解析卖出数量（如果有）
            if portion_raw:
                instruction_type, sell_quantity = cls._parse_sell_quantity(portion_raw)
            else:
                # 默认止盈全部
                instruction_type = InstructionType.CLOSE.value
                sell_quantity = None
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=instruction_type,
                ticker=ticker,
                price=price,
                price_range=price_range,
                sell_quantity=sell_quantity,
                message_id=message_id
            )
        
        # 尝试模式16: ticker+剩下部分+也+价格+附近出（如: nvda剩下部分也2.45附近出）
        match = cls.TAKE_PROFIT_PATTERN_16.search(message)
        if match:
            ticker = match.group(1).upper()
            price_str = match.group(2)
            
            # 解析价格
            price, price_range = cls._parse_price_range(price_str)
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.CLOSE.value,
                ticker=ticker,
                price=price,
                price_range=price_range,
                message_id=message_id
            )
        
        # 尝试模式17: ticker+strike+call/put+...+价格+出
        # 示例: iren 46 call 快进入46价内了 可以剩下的1.6-1.7分批出（支持小写ticker）
        match = cls.TAKE_PROFIT_PATTERN_17.search(message)
        if match:
            ticker = match.group(1).upper()
            strike = float(match.group(2))
            option_type_str = match.group(3).upper()
            option_type = 'CALL' if option_type_str.startswith('CALL') else 'PUT'
            price_str = match.group(4)
            
            # 处理价格中的中文句号（1。7 → 1.7，作为小数点）
            price_str = price_str.replace('。', '.')
            
            # 解析价格
            price, price_range = cls._parse_price_range(price_str)
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.CLOSE.value,
                ticker=ticker,
                option_type=option_type,
                strike=strike,
                price=price,
                price_range=price_range,
                message_id=message_id
            )
        
        # 尝试模式18（兜底）: 纯文本清仓/卖出指令（如: "全部卖出", "清仓"）
        # 这种情况下没有价格、股票等信息，需要通过上下文补全
        # 注意：只匹配完整的短语，避免误匹配带价格的指令
        simple_close_keywords = ['全部卖出', '清仓', '平仓']
        simple_sell_keywords = ['卖出一半', '减仓']
        
        message_stripped = message.strip()
        
        # 检查是否为简单清仓指令（精确匹配或非常短的消息）
        for keyword in simple_close_keywords:
            if message_stripped == keyword or (keyword in message_stripped and len(message_stripped) < 10):
                return OptionInstruction(
                    raw_message=message,
                    instruction_type=InstructionType.CLOSE.value,
                    message_id=message_id
                )
        
        # 检查是否为简单卖出指令
        for keyword in simple_sell_keywords:
            if message_stripped == keyword or (keyword in message_stripped and len(message_stripped) < 15):
                return OptionInstruction(
                    raw_message=message,
                    instruction_type=InstructionType.SELL.value,
                    message_id=message_id
                )
        
        return None
    
    @classmethod
    def parse_multi_line(cls, text: str) -> list[OptionInstruction]:
        """
        解析多行文本，返回所有识别的指令
        
        Args:
            text: 包含多行的文本
            
        Returns:
            解析出的指令列表
        """
        instructions = []
        lines = text.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            instruction = cls.parse(line)
            if instruction:
                instructions.append(instruction)
        
        return instructions


# 测试用例
if __name__ == "__main__":
    test_messages = [
        "INTC - $48 CALLS 本周 $1.2",
        "小仓位  止损 0.95",
        "1.75出三分之一",
        "止损提高到1.5",
        "1.65附近出剩下三分之二",
        "AAPL $150 PUTS 1/31 $2.5",
        "TSLA - 250 CALL $3.0 小仓位",
        "2.0 出一半",
        "止损调整到 1.8",
    ]
    
    print("=" * 60)
    print("期权指令解析测试")
    print("=" * 60)
    
    for msg in test_messages:
        print(f"\n原始消息: {msg}")
        instruction = OptionParser.parse(msg)
        if instruction:
            print(f"解析结果: {instruction}")
            print(f"JSON: {instruction.to_json()}")
        else:
            print("解析结果: 未能识别")
