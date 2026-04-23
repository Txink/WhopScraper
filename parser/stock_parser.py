"""
正股指令解析器
解析正股买卖交易信号。
支持「关注列表先匹配」：当正则未命中 ticker 时，用 config/watched_stocks.json 中的关注股票名在消息中匹配，
命中后再解析买入/卖出价格与数量。
"""
import re
import hashlib
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Tuple, List

from models.instruction import InstructionType
from models.stock_instruction import StockInstruction

try:
    from utils.watched_stocks import get_watched_tickers
except ImportError:
    get_watched_tickers = None  # 测试或无 utils 时

try:
    from utils.ticker_aliases import normalize_message as _normalize_aliases
except ImportError:
    _normalize_aliases = None  # 测试或无 utils 时


class StockParser:
    """正股指令解析器"""

    BUY_PATTERN_1 = re.compile(
        r'([A-Z]{2,5})\s+(?:买入|买了?|建仓了?)\s*\$?(\d+(?:\.\d+)?)',
        re.IGNORECASE
    )
    BUY_PATTERN_2 = re.compile(
        r'(?:买入|买|建仓)\s+([A-Z]{2,5})\s+(?:在|价格)?\s*\$?(\d+(?:\.\d+)?)',
        re.IGNORECASE
    )
    BUY_PATTERN_3 = re.compile(
        r'([A-Z]{2,5})\s+\$?(\d+(?:\.\d+)?)\s*(?:买入|买了?|建仓了?)',
        re.IGNORECASE
    )

    SELL_PATTERN_1 = re.compile(
        r'([A-Z]{2,5})\s+(?:卖出|卖|出)\s+\$?(\d+(?:\.\d+)?)',
        re.IGNORECASE
    )
    SELL_PATTERN_2 = re.compile(
        r'(?:卖出|卖|出|平仓)\s+([A-Z]{2,5})\s+(?:在|价格)?\s*\$?(\d+(?:\.\d+)?)',
        re.IGNORECASE
    )
    SELL_PATTERN_3 = re.compile(
        r'([A-Z]{2,5})\s+\$?(\d+(?:\.\d+)?)\s+(?:卖出|卖|出)',
        re.IGNORECASE
    )

    STOCK_STOP_LOSS_PATTERN = re.compile(
        r'(?:([A-Z]{2,5})\s+)?(?:止损|SL|stop\s*loss)\s+(?:([A-Z]{2,5})\s+)?(?:在)?\s*\$?(\d+(?:\.\d+)?)',
        re.IGNORECASE
    )
    STOCK_TAKE_PROFIT_PATTERN = re.compile(
        r'(?:([A-Z]{2,5})\s+)?(?:止盈|TP|take\s*profit)\s+(?:([A-Z]{2,5})\s+)?(?:在)?\s*\$?(\d+(?:\.\d+)?)'
        r'(?:\s+出\s*(一半|三分之一|三分之二|全部|1/2|1/3|2/3))?',
        re.IGNORECASE
    )

    POSITION_SIZE_PATTERN = re.compile(
        r'(小仓位|中仓位|大仓位|轻仓|重仓|半仓|满仓|常规仓的一半|常规一半|常规的一半)',
        re.IGNORECASE
    )

    # 口语化买入：tsll 在16.02附近开个底仓 / rklb可以40.5介入一半 / bmnr可以34.5附近做点配置
    BUY_PATTERN_4 = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,20}?(?:在[到了]?\s*|可以\s*)?(\d+(?:\.\d+)?)\s*附近\s*[\s\S]{0,10}?(?:开个?底仓|开底仓|建个?(?:小仓位)?底仓|建仓一?笔?|先?建仓|建点|加仓|加(?!密)|介入|(?:做点)?配置|在?接(?!下))',
        re.IGNORECASE
    )
    BUY_PATTERN_5 = re.compile(
        r'(\d+(?:\.\d+)?)[^A-Za-z]{0,10}?(?:加了|加(?!仓))\s*(?:了)?[^A-Za-z]*([A-Za-z]{2,5})\b',
        re.IGNORECASE
    )
    BUY_PATTERN_6 = re.compile(
        r'(\d+(?:\.\d+)?)\s*附近?(?:加回|加)\s*(?:了)?[^A-Za-z]*([A-Za-z]{2,5})\b',
        re.IGNORECASE
    )
    BUY_PATTERN_7 = re.compile(
        r'(\d+(?:\.\d+)?)\s*附近?\s*加(?:了)?(?:\s*个)?\s*([A-Za-z]{2,5})\b',
        re.IGNORECASE
    )
    BUY_PATTERN_8 = re.compile(
        r'([A-Za-z]{2,5})\s*(\d+(?:\.\d+)?)\s*(?:在)?吸回',
        re.IGNORECASE
    )

    # 口语化卖出：提取卖出价、ticker、参考买入价、比例
    SELL_PATTERN_4 = re.compile(
        r'([A-Za-z]{2,5})\s+.*?(\d+(?:\.\d+)?)\s*附近可以出',  # tsll ... 16.04附近可以出
        re.IGNORECASE
    )
    SELL_PATTERN_5 = re.compile(
        r'([A-Za-z]{2,5})?.*?(\d+(?:\.\d+)?)\s*可以出\s*(\d+(?:\.\d+)?)\s*(?:的)?(一半)?',  # 16.4可以出15.43的一半
        re.IGNORECASE
    )
    SELL_PATTERN_6 = re.compile(
        r'(\d+(?:\.\d+)?)\s*出\s*之前\s*(\d+(?:\.\d+)?)\s*剩下(一半)?[^A-Za-z]*([A-Za-z]{2,5})\b',  # 15.75出之前15.45剩下一半tsll
        re.IGNORECASE
    )
    SELL_PATTERN_7 = re.compile(
        r'([A-Za-z]{2,5})\s+.*?可以\s*(\d+(?:\.\d+)?)\s*出\s*(\d+(?:\.\d+)?)\s*的',  # tsll 可以15.3出15.17的
        re.IGNORECASE
    )
    SELL_PATTERN_8 = re.compile(
        r'([A-Za-z]{2,5})\s+.*?(\d+(?:\.\d+)?)\s*可以\s*在?出\s*(\d+(?:\.\d+)?)\s*那部分',  # tsll 在到15.76可以在出15.48那部分
        re.IGNORECASE
    )
    # ticker+...+出+gap+price+那部分/那笔/部分: "nvdl今天注意分时转弯时候出84.5那部分" / "bmnr 这轮上去 出昨天收盘买的30.4部分"
    SELL_TICKER_OUT_PRICE_PART = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,60}?出[\s\S]{0,20}?(\d+(?:\.\d+)?)\s*(?:那部分|那笔|部分)',
        re.IGNORECASE
    )
    # ticker+可以+price+(附近)?+出: "nvdl可以86.75 出" / "nvdl可以86.75附近出"
    SELL_TICKER_CAN_PRICE_OUT = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,30}?可以\s*(\d+(?:\.\d+)?)\s*(?:附近)?\s*出(?!现|来)',
        re.IGNORECASE
    )
    SELL_REF_YESTERDAY = re.compile(r'昨天\s*(\d+(?:\.\d+)?)\s*的')  # 昨天16.02的

    # ===== 新增卖出模式 =====
    # 9. 价格区间 + 一半: "19.8-19.9附近出掉剩下一半" / "20-20.1出一半"
    SELL_RANGE_HALF = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,60}?(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)\s*(?:附近)?\s*[\s\S]{0,15}?(?:出掉?|减掉?)\s*(?:剩下的?|另外的?)?一半',
        re.IGNORECASE
    )
    # 10. 单价 + 一半: "19.6附近出一半" / "出掉一半" / "剩下一半"
    SELL_SINGLE_HALF = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,60}?(\d+(?:\.\d+)?)\s*(?:附近)?\s*[\s\S]{0,15}?(?:出掉?|减掉?)\s*(?:剩下的?|另外的?)?一半',
        re.IGNORECASE
    )
    # 10b. ticker+一半+在+price+出: "nvdl之前剩下的一半在107.5出"
    SELL_HALF_AT_PRICE = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,40}?一半[\s\S]{0,20}?在?\s*(\d+(?:\.\d+)?)\s*(?:附近)?出(?!现|来)',
        re.IGNORECASE
    )
    # 10c. ticker+price+附近+也?出点: "nvdl上周五剩下点仓位 在盘前90.9附近也出点"
    SELL_ALSO_OUT_SOME = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,60}?(\d+(?:\.\d+)?)\s*(?:附近)?\s*[\s\S]{0,15}?(?:也|可以)?出(?:掉|了)?(?:些?点)',
        re.IGNORECASE
    )
    # 11. 价格出一半+参考价: "14.31出一半 14吸的" / "15.34出剩下一半14.6吸的tsll"
    SELL_HALF_WITH_REF = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,15}?(\d+(?:\.\d+)?)\s*出\s*(?:剩下的?)?一半\s*(\d+(?:\.\d+)?)\s*(?:吸的|买的|加的)?',
        re.IGNORECASE
    )
    # 12. "XX时候减掉 YY加仓的": "19时候减掉 18.3加仓的"
    SELL_TIME_REDUCE = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,20}?(\d+(?:\.\d+)?)\s*时候\s*减掉?\s*(\d+(?:\.\d+)?)\s*(?:加仓的|买的|加的)?',
        re.IGNORECASE
    )
    # 13. 价格区间 + 分批出/减点
    SELL_RANGE_PARTIAL = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,60}?(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)\s*(?:附近)?\s*(?:分批出|减点|减掉点)',
        re.IGNORECASE
    )
    # 14. 价格区间 + 出/减 (通用，附近后允许少量内容)
    SELL_RANGE_FULL = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,60}?(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)\s*(?:附近)?\s*[\s\S]{0,20}?(?:出掉?|减掉?)',
        re.IGNORECASE
    )
    # 14b. 价格区间+之间: "19.6-19.8之间" (出的意思隐含)
    SELL_RANGE_BETWEEN = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,60}?(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)\s*(?:之间|到)\s*(?:出|都出)?',
        re.IGNORECASE
    )
    # 15. 单价 + 减点/分批出 (附近后允许少量内容)
    SELL_PARTIAL = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,60}?(\d+(?:\.\d+)?)\s*(?:附近)?\s*[\s\S]{0,20}?(?:减掉?点|分批出)',
        re.IGNORECASE
    )
    # 16. 单价 + 减 (不带具体比例)
    SELL_REDUCE = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,60}?(\d+(?:\.\d+)?)\s*(?:附近)?\s*[\s\S]{0,10}?减(?!点|掉点)',
        re.IGNORECASE
    )
    # 16b. ticker + price + 附近卖出: "oklo盘前冲高94附近卖出"
    SELL_PRICE_SELL_OUT = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,60}?(\d+(?:\.\d+)?)\s*(?:附近)?\s*卖出',
        re.IGNORECASE
    )
    # 17. 短线出: "18.45出短线" / "95.1附近出短线"
    SELL_SHORT_TERM = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,30}?(\d+(?:\.\d+)?)\s*(?:附近)?\s*出短线',
        re.IGNORECASE
    )
    # 19a. 单价附近出+参考价+的一半: "15.39附近出 15.05的一半" (优先于通用OUT_REF)
    SELL_APPROX_OUT_REF_HALF = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,30}?(\d+(?:\.\d+)?)\s*(?:附近)?\s*出\s*(\d+(?:\.\d+)?)\s*(?:买的|吸的|加的)?的?\s*一半',
        re.IGNORECASE
    )
    # 19. 单价附近出+参考买入价: "17.45附近出17.35买的" / "17.77附近也把17.98买的出了"
    SELL_APPROX_OUT_REF = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,30}?(\d+(?:\.\d+)?)\s*(?:附近)?[^出]{0,15}?出\s*(?:了)?\s*(\d+(?:\.\d+)?)\s*(?:买的|吸的|加的)?',
        re.IGNORECASE
    )
    # 20. "把XX买的出了": "17.77附近也把节前17.98买的出了"
    SELL_PUT_OUT_REF = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,30}?(\d+(?:\.\d+)?)\s*(?:附近)?\s*[\s\S]{0,15}?把\s*(?:节前)?(?:\S+)?\s*(\d+(?:\.\d+)?)\s*(?:买的|吸的)\s*出(?:了)?',
        re.IGNORECASE
    )
    # 21. 简单附近出: "19.45附近 出" / "47.7成本附近先出" / "0.4附近都出"
    SELL_APPROX_SIMPLE = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,60}?(\d+(?:\.\d+)?)\s*(?:成本)?附近\s*(?:都|也|先)?(?:卖)?出(?:\s|$|了|掉)',
        re.IGNORECASE
    )
    # 22. "出之前XX吸的" (SELL_PATTERN_6简化版，不要求剩下)
    SELL_OUT_BEFORE_REF = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,15}?(\d+(?:\.\d+)?)\s*出\s*(?:之前)?\s*(\d+(?:\.\d+)?)\s*(?:吸的|买的|加的)',
        re.IGNORECASE
    )
    # 23. XX那部分...出: "tsll 19.1 那部分到转弯时候也出" (卖出参考买入价那部分)
    SELL_THAT_PART = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,10}?(\d+(?:\.\d+)?)\s*那部分[\s\S]{0,30}?出',
        re.IGNORECASE
    )
    # 24. 出昨天/之前XX买的那部分: "出昨天15.04买的那部分"
    SELL_YESTERDAY_BUY_PART = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,50}?出\s*(?:昨天|之前|上次)?\s*(\d+(?:\.\d+)?)\s*(?:买的|吸的|加的)\s*那部分',
        re.IGNORECASE
    )

    # ===== 新增买入模式 =====
    # 9. 价格区间 + 回吸/吸回/低吸 (附近后允许少量内容)
    BUY_RANGE_ABSORB = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,60}?(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)\s*(?:附近)?\s*[\s\S]{0,15}?(?:支撑)?(?:分批)?(?:回吸|吸回|低吸|吸(?!筹))',
        re.IGNORECASE
    )
    # 12b. ticker + 吸 + range: "nvdl今天还是转弯时候吸 83-83.5" (action before range)
    BUY_TICKER_ACTION_RANGE = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,50}?(?:吸|回吸|吸回|低吸|加|接)\s*(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)',
        re.IGNORECASE
    )
    # 10. 价格区间 + 在回吸/回吸: "15.1-15在回吸今天卖出的部分"
    BUY_RANGE_RETRACE = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,40}?(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)\s*(?:在)?(?:回吸|吸回)',
        re.IGNORECASE
    )
    # 11. 价格区间 + 建仓/买一半/加一笔
    BUY_RANGE_BUILD = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,60}?(?:在\s*)?(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)\s*(?:附近)?\s*[\s\S]{0,15}?(?:建个?小仓位|建底仓|建仓|开个?(?:小仓位|常规仓)?仓?|加仓|加点仓?|加一笔|加一半|分批(?:进|加)|进|买一半|买)',
        re.IGNORECASE
    )
    # 12. 回踩+单价+回吸: "回踩15.05回吸" / "回踩20.3时候建点"
    BUY_RETRACE = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,30}?回踩\s*(\d+(?:\.\d+)?)\s*(?:回吸|建点|时候建点|低吸)',
        re.IGNORECASE
    )
    # 13. 单价 + 回吸/吸回/低吸/吸 (包含"可以/在"前缀和"一笔/一半"后缀变体)
    BUY_ABSORB_SINGLE = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,50}?(\d+(?:\.\d+)?)\s*(?:附近)?\s*(?:可以\s*|在\s*)?(?:回吸|吸回|低吸|吸(?!筹))(?:一笔|一半|点)?',
        re.IGNORECASE
    )
    # 13b. "XX回吸/吸" (价格直接紧跟回吸/吸回/吸): "19.4回吸点" / "14.6回吸常规的一半" / "80.65也是吸一半"
    BUY_PRICE_ABSORB = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,30}?(\d+(?:\.\d+)?)\s*(?:也是|在)?\s*(?:回吸|吸回|吸(?!筹|回))(?!\s*之前)',
        re.IGNORECASE
    )
    # 14. 入了仓位 / 先入一笔: "在18.99附近入了仓位" / "tsll在18.8附近回踩支撑附近也是先入一笔"
    BUY_ENTERED = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,20}?(\d+(?:\.\d+)?)\s*(?:附近)?\s*[\s\S]{0,20}?(?:入了?仓位?|入仓|入了|先?入一笔|先入)',
        re.IGNORECASE
    )
    # 15. 挂单在: "可以挂小仓位单在19.2这里"
    BUY_HANG_ORDER = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,40}?挂[^在]{0,15}在\s*(\d+(?:\.\d+)?)\s*(?:这里|附近)?',
        re.IGNORECASE
    )
    # 15b. 挂单的XX的低吸: "后面看挂单的16.64的低吸"
    BUY_HANG_ABSORB = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,50}?挂单[^\d]{0,20}?(\d+(?:\.\d+)?)\s*(?:的)?\s*(?:低吸|回吸|吸)',
        re.IGNORECASE
    )
    # 16. 价格附近接: "15。03附近接" (支持中文句号)
    BUY_CATCH_PRICE = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,50}?(\d+[.。]\d+)\s*(?:附近)?\s*接(?!\s*下)',
        re.IGNORECASE
    )
    # 17. price吸回 ticker: "14附近吸回 tsll 卖出那部分"
    BUY_PRICE_THEN_TICKER = re.compile(
        r'(\d+(?:\.\d+)?)\s*(?:附近)?\s*吸回\s*([A-Za-z]{2,5})',
        re.IGNORECASE
    )
    # 18. 价格区间 + 支撑: "tsll 19.3-19.2 注意下刚打压到支撑了 也是小仓位日内"
    BUY_RANGE_SUPPORT = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,10}?(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)\s*[\s\S]{0,40}?支撑',
        re.IGNORECASE
    )
    # 19. 附近小加: "18.3附近小加" (小仓位买入)
    BUY_SMALL_ADD = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,60}?(\d+(?:\.\d+)?)\s*附近\s*小加',
        re.IGNORECASE
    )
    # 20. 价格XX...这个价格附近吸: "tsll 14点12分价格15.98 二次确认过 可以这个价格附近吸"
    BUY_PRICE_REF_ABSORB = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,60}?价格\s*(\d+(?:\.\d+)?)\s*[\s\S]{0,50}?(?:这个价格|这里|该价格|这个价位)?\s*附近\s*(?:吸|回吸|低吸)',
        re.IGNORECASE
    )
    # 21. 开了一笔/建了一笔: "tsll 18.06 开了一笔常规仓的一半"
    BUY_OPENED_ONE = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,10}?(\d+(?:\.\d+)?)\s*(?:开了一笔|建了一笔|开了一个|建了一个|入了一笔)',
        re.IGNORECASE
    )
    # 22. 回吸在前，价格区间在后: "tsll...回吸...17.8-17.9附近"
    BUY_ABSORB_THEN_RANGE = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,80}?(?:回吸|低吸|吸回)\s*[\s\S]{0,50}?(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)\s*(?:附近)?',
        re.IGNORECASE
    )
    # 23. ticker + price 直接列举 (价格列表买入): "tsll 15.6 rklb 38.3-38.6附近 nvdl 79-80附近"
    BUY_LIST_PRICE = re.compile(
        r'([A-Za-z]{2,5})\s+(\d+(?:\.\d+)?)\s+(?=[A-Za-z]{2,5}\s)',
        re.IGNORECASE
    )

    PORTION_MAP = {
        '三分之一': '1/3',
        '三分之二': '2/3',
        '一半': '1/2',
        '剩下一半': '1/2',
        '另外一半': '1/2',
        '剩下的一半': '1/2',
        '全部': '全部',
        '1/3': '1/3',
        '2/3': '2/3',
        '1/2': '1/2',
    }

    # ===== ticker 在句尾/句中 的买入模式 =====
    # 买入 T1: "19.2附近在小仓位开仓tsll" / "20附近开仓tsll"
    BUY_OPEN_SUFFIX = re.compile(
        r'(\d+(?:[.。]\d+)?)\s*附近\s*(?:在\s*)?(?:小仓位|常规仓)?\s*(?:开仓|建仓)\s*([A-Za-z]{2,5})(?![a-zA-Z0-9])',
        re.IGNORECASE
    )
    # 买入 T2: "19.1-19.15建了点这轮tsll底仓" / "19-19.1加了tsll" / "45.7-45.8附近 开个intc常规仓的一半"
    BUY_RANGE_BUILD_SUFFIX = re.compile(
        r'(\d+(?:[.。]\d+)?)\s*[-~到]\s*(\d+(?:[.。]\d+)?)\s*[\s\S]{0,20}?(?:建了?|买了?|加了?|开了?)\s*(?:点|些|个)?[\s\S]{0,15}?([A-Za-z]{2,5})(?![a-zA-Z0-9])',
        re.IGNORECASE
    )
    # 买入 T3: ticker回吸...看价格 可以价格挂单 "tsll回吸也是看19.4 可以19.43挂个单子"
    BUY_TICKER_ABSORB_HANG = re.compile(
        r'([A-Za-z]{2,5})\s*回吸[\s\S]{0,30}?可以\s*(\d+(?:[.。]\d+)?)\s*挂',
        re.IGNORECASE
    )
    # 买入 T4: 价格+在+吸回+(卖出的)+ticker后缀: "15.40在吸回卖出的tsll"
    BUY_ABSORB_BACK_SUFFIX = re.compile(
        r'(\d+(?:[.。]\d+)?)\s*(?:附近)?\s*在?\s*吸回\s*(?:卖出的|之前卖出的|之前的|卖的)?\s*([A-Za-z]{2,5})(?![a-zA-Z0-9])',
        re.IGNORECASE
    )
    # 买入 T5: 价格+吸了/接回/加了/回吸+ticker 句尾: "17.2附近 吸了tsll" / "14.52盘前加了tsll"
    BUY_PRICE_ACTION_SUFFIX = re.compile(
        r'(\d+(?:[.。]\d+)?)\s*(?:附近)?\s*[\s\S]{0,15}?(?:吸了|接回|回吸了?|加了)\s*[\s\S]{0,10}?([A-Za-z]{2,5})(?![a-zA-Z0-9])',
        re.IGNORECASE
    )
    # 买入 T5b: 价格+加仓了+ticker（紧跟，不允许间隔，避免"减仓...加仓的"误匹配）: "14.05加仓了tsll"
    BUY_PRICE_ADD_POSITION_SUFFIX = re.compile(
        r'(\d+(?:[.。]\d+)?)\s*加仓了?\s*([A-Za-z]{2,5})(?![a-zA-Z0-9])',
        re.IGNORECASE
    )
    # 买入 T6: 价格+常规仓/小仓位+的+ticker+接回/吸回: "尾盘17.97常规仓一半的tsll接回"
    BUY_POSITION_TICKER_ACTION = re.compile(
        r'(\d+(?:[.。]\d+)?)\s*(?:常规仓的?一半|常规一半|常规的一半|小仓位|常规仓)\s*的?\s*([A-Za-z]{2,5})\s*(?:接回|接|吸回)',
        re.IGNORECASE
    )
    # 买入 T7: 回吸了+仓位描述+ticker+在+价格: "盘前回吸了常规一半的tsll在16.38"
    BUY_ACTION_TICKER_AT_PRICE = re.compile(
        r'(?:回吸了?|吸回了?|加了)\s*[\s\S]{0,20}?([A-Za-z]{2,5})\s*(?:在|@)\s*(\d+(?:[.。]\d+)?)',
        re.IGNORECASE
    )

    # ===== ticker 在句尾/句中 的卖出模式 =====
    # 卖出 T1: "21.2-21.4之间减仓tsll" / "20.5-20.6附近可以减点剩下的tsll"
    SELL_RANGE_REDUCE_SUFFIX = re.compile(
        r'(\d+(?:[.。]\d+)?)\s*[-~到]\s*(\d+(?:[.。]\d+)?)\s*(?:附近|之间|这段)?\s*[\s\S]{0,15}?(?:减仓|减持|减点|减掉|减|出)\s*[\s\S]{0,15}?([A-Za-z]{2,5})(?![a-zA-Z0-9])',
        re.IGNORECASE
    )
    # 卖出 T2: "20.6到20.9这段分批出昨天20。5的tsll"
    SELL_BATCH_REF_SUFFIX = re.compile(
        r'(\d+(?:[.。]\d+)?)\s*[-~到]\s*(\d+(?:[.。]\d+)?)\s*(?:这段|附近)?\s*分批出\s*(?:昨天|之前)?\s*(\d+(?:[.。]\d+)?)\s*的?\s*([A-Za-z]{2,5})(?![a-zA-Z0-9])',
        re.IGNORECASE
    )
    # 卖出 T3: "19.7到19.8出 tsll" / "16出tsll"
    SELL_PRICE_OUT_SUFFIX = re.compile(
        r'(\d+(?:[.。]\d+)?)\s*(?:[-~到]\s*(\d+(?:[.。]\d+)?))?\s*(?:附近)?\s*(?:可以\s*)?出\s*([A-Za-z]{2,5})(?![a-zA-Z0-9])',
        re.IGNORECASE
    )
    # 卖出 T5: 价格区间+附近出+参考价+的+ticker: "11.65-11.7附近出11.16的eose剩下一半"
    SELL_RANGE_OUT_REF_SUFFIX = re.compile(
        r'(\d+(?:[.。]\d+)?)\s*[-~]\s*(\d+(?:[.。]\d+)?)\s*附近?\s*出\s*(\d+(?:[.。]\d+)?)\s*(?:的|吸的|买的|加的)\s*([A-Za-z]{2,5})(?![a-zA-Z0-9])',
        re.IGNORECASE
    )

    # 卖出 T4: "19.4出一半18.8的tsll" / "15.34出剩下一半14.6吸的tsll" / "135附近出一半 132的pltr"
    SELL_HALF_REF_SUFFIX = re.compile(
        r'(\d+(?:[.。]\d+)?)\s*(?:附近)?\s*出\s*(?:剩下的?)?一半\s*(\d+(?:[.。]\d+)?)\s*(?:吸的|买的|加的|的)\s*([A-Za-z]{2,5})(?![a-zA-Z0-9])',
        re.IGNORECASE
    )
    # 卖出 T7: 单价+(附近)?+出+中间内容+参考价+(附近)?+的/那部分+ticker 句尾
    SELL_PRICE_OUT_REF_SUFFIX = re.compile(
        r'(\d+(?:[.。]\d+)?)\s*(?:附近)?\s*(?:可以)?(?:再次?)?出(?:了|掉)?\s*[\s\S]{0,25}?(\d+(?:[.。]\d+)?)\s*(?:附近)?(?:的那部分|那部分|的|低吸的|低买的|吸的|买的|加的)\s*([A-Za-z]{2,5})(?![a-zA-Z0-9])',
        re.IGNORECASE
    )
    # 卖出 T7b: 单价+出一半+ticker (无ref): "86出一半nvdl" / "94.3出一半nvdl"
    SELL_OUT_HALF_NO_REF_SUFFIX = re.compile(
        r'(\d+(?:[.。]\d+)?)\s*(?:附近)?\s*(?:再)?出\s*(?:掉)?(?:剩下的?)?一半\s*[\s\S]{0,10}?([A-Za-z]{2,5})(?![a-zA-Z0-9])',
        re.IGNORECASE
    )
    # 卖出 T7c: 单价+附近+出掉/出+gap+ticker (无ref): "92附近出之前的nvdl底仓" / "76.4附近出盘前买的nvdl"
    SELL_APPROX_OUT_TICKER_SUFFIX = re.compile(
        r'(\d+(?:[.。]\d+)?)\s*(?:附近|近)\s*(?:可以)?(?:再)?出(?:了|掉)?[\s\S]{0,20}?([A-Za-z]{2,5})(?![a-zA-Z0-9])',
        re.IGNORECASE
    )
    # 卖出 T7d: 单价+出+gap+ticker (无"附近"): "43.1出夜盘补的iren那部分" / "75.1出日内买的rklb" / "32.6出个三分之一bmnr"
    SELL_PRICE_OUT_GAP_TICKER_SUFFIX = re.compile(
        r'(\d+(?:[.。]\d+)?)\s*(?:附近)?\s*出[\s\S]{0,20}?([A-Za-z]{2,5})(?![a-zA-Z0-9])',
        re.IGNORECASE
    )

    # 买入 T4b: 单价+附近+gap+吸/接/加/进+gap+ticker (后缀)
    BUY_APPROX_ACTION_TICKER_SUFFIX = re.compile(
        r'(\d+(?:[.。]\d+)?)\s*(?:附近)?\s*[\s\S]{0,15}?(?:回吸|吸回|吸(?!筹)|接|进(?!场|行)|加(?!仓|密))\s*[\s\S]{0,10}?([A-Za-z]{2,5})(?![a-zA-Z0-9])',
        re.IGNORECASE
    )
    # 买入 T4c: 单价+附近+开仓/开仓了+仓位+的+ticker: "夜盘83附近开仓了常规仓一半的nvdl"
    BUY_OPEN_POSITION_TICKER_SUFFIX = re.compile(
        r'(\d+(?:[.。]\d+)?)\s*附近\s*开仓了?\s*[\s\S]{0,20}?([A-Za-z]{2,5})(?![a-zA-Z0-9])',
        re.IGNORECASE
    )
    # 买入 T8: 单价+(附近)?+(可以)?+加仓/建仓/配置/买回/接回/回买+ticker 句尾
    # "321附近可以加仓mstr" / "6.7附近建仓个新的 bbai" / "3.68附近买回之前卖出的rxrx"
    # "194接回 常规一半的 之前218卖出的amd" / "21附近配置点mara"
    # 约束：
    #   - 价格后不跟"分/秒"，避免把"18点30分"的"30"当价格
    #   - ticker 最少 3 字符 + 两侧 boundary，避免从 openai/ai叙事 错抽 AI/PENAI
    #   - 不含"介入"动词，因"人工介入"等非交易语义在议论性消息中过多
    BUY_VERBOSE_ACTION_SUFFIX = re.compile(
        r'(\d+(?:[.。]\d+)?)(?![分秒])\s*(?:附近)?\s*[\s\S]{0,15}?'
        r'(?:加仓|建仓了?|配置点?|买回|接回|回买)'
        r'\s*[\s\S]{0,25}?(?<![a-zA-Z0-9])([A-Za-z]{3,5})(?![a-zA-Z0-9])',
        re.IGNORECASE
    )

    # 卖出 T8: 单价+减仓/减点/减+ticker 句尾: "21.7也减仓点tsll" / "22附近也可以减点tsll" / "17附近再减点tsll"
    SELL_SINGLE_REDUCE_SUFFIX = re.compile(
        r'(\d+(?:[.。]\d+)?)\s*(?:附近)?\s*[\s\S]{0,20}?(?:减仓|减持|减点|减)\s*[\s\S]{0,20}?([A-Za-z]{2,5})(?![a-zA-Z0-9])',
        re.IGNORECASE
    )
    # 卖出 T9: 单价+减一半+参考价+ticker 句尾: "17附近减一半16.64挂单进的tsll" / "17.88减一半17.4附近的tsll"
    SELL_REDUCE_HALF_REF_SUFFIX = re.compile(
        r'(\d+(?:[.。]\d+)?)\s*(?:附近)?\s*减一半\s*(\d+(?:[.。]\d+)?)\s*(?:附近的|挂单进的|的|吸的|买的|加的)?\s*([A-Za-z]{2,5})(?![a-zA-Z0-9])',
        re.IGNORECASE
    )

    # ===== 关注列表 fallback：用 watched_stocks 命中 ticker 后，仅用下列正则匹配价格/操作/数量 =====
    SELL_HINT_RANGE_CAN_OUT = re.compile(
        r'(\d+(?:[.。]\d+)?)\s*[-~]\s*(\d+(?:[.。]\d+)?)\s*附近可以出',
        re.IGNORECASE
    )
    SELL_HINT_RANGE_OUT = re.compile(
        r'(\d+(?:[.。]\d+)?)\s*[-~]\s*(\d+(?:[.。]\d+)?)\s*附近?\s*[\s\S]{0,30}?(?:出|减)',
        re.IGNORECASE
    )
    SELL_HINT_SINGLE_OUT = re.compile(
        r'(\d+(?:[.。]\d+)?)\s*(?:成本)?(?:附近)?[\s\S]{0,15}?(?:可以\s*)?(?:都|也|先)?(?:卖出|出)(?!现|来|了?短线)',
        re.IGNORECASE
    )
    SELL_HINT_SINGLE_HALF = re.compile(
        r'(\d+(?:[.。]\d+)?)\s*出\s*(?:剩下的?)?一半',
        re.IGNORECASE
    )
    SELL_HINT_REDUCE = re.compile(
        r'(\d+(?:[.。]\d+)?)\s*(?:附近)?\s*[\s\S]{0,20}?(?:减仓|减持|减点|减)',
        re.IGNORECASE
    )
    BUY_HINT_RANGE = re.compile(
        r'(\d+(?:[.。]\d+)?)\s*[-~]\s*(\d+(?:[.。]\d+)?)\s*附近?\s*[\s\S]{0,30}?(?:回吸|吸回|吸|加|建仓|开仓|介入|配置|分批进|分批加|进|接)',
        re.IGNORECASE
    )
    BUY_HINT_SINGLE = re.compile(
        r'(\d+(?:[.。]\d+)?)(?![分秒])\s*(?:附近)?\s*[\s\S]{0,20}?(?:加(?!仓|密)|吸回|回吸|吸(?!筹)|开仓|建仓|(?<!人工)介入|(?:做点)?配置|开(?!盘|始|涨|跌|低|高)|进(?!场|行)|接(?!下)|回买)',
        re.IGNORECASE
    )
    # 止盈口语化：价格（单价或区间）+ 全部/都/先 + 止盈（+ 一半/一点/一部分/了?）
    # "15.9全部止盈" / "7.2-7.3都止盈" / "47.7附近止盈一半" / "216-217止盈196的" / "都止盈一些"
    TP_HINT = re.compile(
        r'(\d+(?:[.。]\d+)?)(?![分秒])\s*(?:[-~到]\s*(\d+(?:[.。]\d+)?))?\s*(?:附近)?\s*'
        r'[\s\S]{0,20}?(?:全部|都|先)?\s*止盈(?:一半|一点|一部分|了)?',
        re.IGNORECASE
    )
    # 止盈口语化（价格在动词后）："都止盈 45-46附近"
    TP_HINT_POST = re.compile(
        r'止盈(?:一半|一点|一部分|了)?\s*(?:在)?\s*\$?'
        r'(\d+(?:[.。]\d+)?)(?![分秒])(?:\s*[-~到]\s*(\d+(?:[.。]\d+)?))?',
        re.IGNORECASE
    )
    # 止损口语化：价格（单价或区间）+ 全部/都/先 + 止损（+ 了?）
    # "42.15附近...先止损了"
    SL_HINT = re.compile(
        r'(\d+(?:[.。]\d+)?)(?![分秒])\s*(?:[-~到]\s*(\d+(?:[.。]\d+)?))?\s*(?:附近)?\s*'
        r'[\s\S]{0,20}?(?:全部|都|先)?\s*止损(?:一半|一点|了)?',
        re.IGNORECASE
    )
    # 止损口语化（价格在动词后）："止损 20.2"
    SL_HINT_POST = re.compile(
        r'止损(?:一半|一点|了)?\s*(?:在)?\s*\$?(\d+(?:[.。]\d+)?)(?![分秒])',
        re.IGNORECASE
    )

    @classmethod
    def parse(cls, message: str, message_id: Optional[str] = None, message_timestamp: Optional[str] = None) -> Optional[StockInstruction]:
        """
        解析消息文本，返回股票指令。
        Args:
            message: 原始消息文本
            message_id: 消息唯一标识（用于去重）
            message_timestamp: 消息时间戳（可选）
        Returns:
            StockInstruction 或 None
        """
        message = message.strip().replace('。', '.')
        message = message.replace('\u2013', '-').replace('\u2014', '-').replace('\u2012', '-').replace('\u2015', '-')
        if not message:
            return None

        if not message_id:
            message_id = hashlib.md5(message.encode()).hexdigest()[:12]

        instruction = cls._parse_buy(message, message_id)
        if instruction:
            return instruction
        instruction = cls._parse_sell(message, message_id)
        if instruction:
            return instruction
        instruction = cls._parse_stop_loss(message, message_id)
        if instruction:
            return instruction
        instruction = cls._parse_take_profit(message, message_id)
        if instruction:
            return instruction
        # 关注列表 fallback：用 config/watched_stocks.json 中的 ticker 在消息中做整词匹配，命中后再解析价格/数量
        for ticker in cls._watched_tickers_in_message(message):
            instruction = cls._parse_with_watched_ticker(message, message_id, ticker)
            if instruction:
                return instruction
        # 中文昵称 fallback：把"博通/奈飞双倍/微软双倍"等替换为 ticker 再重试
        if _normalize_aliases:
            normalized = _normalize_aliases(message)
            if normalized != message:
                for fn in (cls._parse_buy, cls._parse_sell, cls._parse_stop_loss, cls._parse_take_profit):
                    instruction = fn(normalized, message_id)
                    if instruction:
                        return instruction
                for ticker in cls._watched_tickers_in_message(normalized):
                    instruction = cls._parse_with_watched_ticker(normalized, message_id, ticker)
                    if instruction:
                        return instruction
        return None

    # 买入：数量按历史参考
    BUY_REF_FRIDAY = re.compile(r'周五卖出的', re.IGNORECASE)
    BUY_REF_TODAY = re.compile(r'今天卖出的', re.IGNORECASE)
    BUY_REF_PART = re.compile(r'卖出的一部分', re.IGNORECASE)

    @classmethod
    def _normalize_price(cls, s: str) -> float:
        """将含中文句号的价格字符串转为 float，如 '15。03' -> 15.03。"""
        return float(str(s).replace('。', '.'))

    @classmethod
    def _round2(cls, x: float) -> float:
        """标准四舍五入保留2位小数（避免 Python round() 银行家舍入问题）。"""
        return float(Decimal(str(x)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))

    @classmethod
    def _resolve_position_size(cls, message: str) -> Optional[str]:
        """
        统一解析买入仓位描述：
        1. 优先匹配 POSITION_SIZE_PATTERN（小仓位/常规仓的一半等）
        2. 其次检测独立的"一半"（如"吸回一半"）
        """
        pos = cls.POSITION_SIZE_PATTERN.search(message)
        if pos:
            return pos.group(1)
        if '一半' in message:
            return '一半'
        return None

    @classmethod
    def _sort_range(cls, p1: float, p2: float) -> Tuple[float, float]:
        """确保价格区间低价在前。"""
        return (min(p1, p2), max(p1, p2))

    @classmethod
    def _watched_tickers_in_message(cls, message: str) -> List[str]:
        """从 config/watched_stocks.json 关注列表中找出在消息里出现的 ticker（整词匹配），按长度降序。"""
        if not get_watched_tickers:
            return []
        watched = get_watched_tickers()
        if not watched:
            return []
        found = []
        # 使用 [^a-zA-Z] 或首尾作为边界，避免中文等 Unicode 被 \b 当成 \w 导致句尾 tsll 匹配不到
        for t in watched:
            pat = r'(?:^|[^a-zA-Z])' + re.escape(t) + r'(?:$|[^a-zA-Z])'
            if re.search(pat, message, re.IGNORECASE):
                found.append(t)
        return sorted(found, key=len, reverse=True)

    @classmethod
    def _parse_with_watched_ticker(
        cls, message: str, message_id: str, ticker: str
    ) -> Optional[StockInstruction]:
        """已知 ticker（来自关注列表命中），仅用价格/操作/数量正则解析，不依赖 ticker 在句中的位置。"""
        ticker = (ticker or "").strip().upper()
        if not ticker:
            return None
        # 参考价与比例（那部分 / 一半）
        ref_price = None
        ref_label = None
        if '那部分' in message:
            m = re.search(r'之前\s*(\d+(?:[.。]\d+)?)\s*那部分', message)
            if m:
                ref_price = cls._normalize_price(m.group(1))
                ref_label = f"之前{ref_price}那部分"
        if '一半' in message:
            m = re.search(r'(\d+(?:[.。]\d+)?)\s*的一半', message)
            if m:
                ref_price = cls._normalize_price(m.group(1))
                ref_label = f"{ref_price}的一半"
        sell_quantity = '1/2' if '一半' in message else '全部'

        # 卖出：价格区间 + 附近可以出 / 出 / 减
        match = cls.SELL_HINT_RANGE_CAN_OUT.search(message)
        if match:
            lo, hi = cls._sort_range(cls._normalize_price(match.group(1)), cls._normalize_price(match.group(2)))
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=cls._round2((lo + hi) / 2),
                price_range=[lo, hi],
                sell_quantity=sell_quantity,
                sell_reference_price=ref_price,
                sell_reference_label=ref_label,
                message_id=message_id
            )
        match = cls.SELL_HINT_RANGE_OUT.search(message)
        if match:
            lo, hi = cls._sort_range(cls._normalize_price(match.group(1)), cls._normalize_price(match.group(2)))
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=cls._round2((lo + hi) / 2),
                price_range=[lo, hi],
                sell_quantity=sell_quantity,
                sell_reference_price=ref_price,
                sell_reference_label=ref_label,
                message_id=message_id
            )
        match = cls.SELL_HINT_SINGLE_OUT.search(message)
        if match:
            price = cls._normalize_price(match.group(1))
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=price,
                sell_quantity=sell_quantity,
                sell_reference_price=ref_price,
                sell_reference_label=ref_label,
                message_id=message_id
            )
        match = cls.SELL_HINT_SINGLE_HALF.search(message)
        if match:
            price = cls._normalize_price(match.group(1))
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=price,
                sell_quantity='1/2',
                sell_reference_price=ref_price,
                sell_reference_label=ref_label,
                message_id=message_id
            )
        match = cls.SELL_HINT_REDUCE.search(message)
        if match:
            price = cls._normalize_price(match.group(1))
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=price,
                sell_quantity=sell_quantity,
                sell_reference_price=ref_price,
                sell_reference_label=ref_label,
                message_id=message_id
            )

        # 止盈：价格（区间或单价）+ 止盈 | 止盈 + 价格
        match = cls.TP_HINT.search(message) or cls.TP_HINT_POST.search(message)
        if match:
            lo = cls._normalize_price(match.group(1))
            hi_s = match.group(2)
            if hi_s:
                hi = cls._normalize_price(hi_s)
                lo, hi = cls._sort_range(lo, hi)
                price = cls._round2((lo + hi) / 2)
                price_range = [lo, hi]
            else:
                price = lo
                price_range = None
            tp_portion = '1/2' if '一半' in message else '全部'
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=price,
                price_range=price_range,
                sell_quantity=tp_portion,
                message_id=message_id
            )
        # 止损：价格 + 止损 | 止损 + 价格
        match = cls.SL_HINT.search(message) or cls.SL_HINT_POST.search(message)
        if match:
            price = cls._normalize_price(match.group(1))
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.MODIFY.value,
                ticker=ticker,
                stop_loss_price=price,
                message_id=message_id
            )

        # 买入：价格区间/单价 + 回吸/加/建仓
        match = cls.BUY_HINT_RANGE.search(message)
        if match:
            lo, hi = cls._sort_range(cls._normalize_price(match.group(1)), cls._normalize_price(match.group(2)))
            position_size = cls._resolve_position_size(message)
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                price=cls._round2((lo + hi) / 2),
                price_range=[lo, hi],
                position_size=position_size,
                message_id=message_id
            )
        match = cls.BUY_HINT_SINGLE.search(message)
        if match:
            price = cls._normalize_price(match.group(1))
            position_size = cls._resolve_position_size(message)
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                price=price,
                position_size=position_size,
                message_id=message_id
            )
        return None

    # 持仓回顾/观察性语句排除：如"回吸一笔也把剩下的放尾盘再看"
    # 这类消息是对已有持仓的描述，而非新的买入操作
    _NON_ACTION_WATCH = re.compile(
        r'(?:回吸|入了?一笔)[\s\S]{0,30}剩下的?(?:放|到)[\s\S]{0,20}再看',
        re.IGNORECASE
    )

    @classmethod
    def _parse_buy(cls, message: str, message_id: str) -> Optional[StockInstruction]:
        # 排除持仓回顾性语句（非新操作）
        if cls._NON_ACTION_WATCH.search(message):
            return None
        # 标准格式
        for pattern in (cls.BUY_PATTERN_1, cls.BUY_PATTERN_2, cls.BUY_PATTERN_3):
            match = pattern.search(message)
            if not match:
                continue
            ticker = match.group(1).upper()
            price = float(match.group(2))
            position_match = cls.POSITION_SIZE_PATTERN.search(message)
            position_size = position_match.group(1) if position_match else None
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                price=price,
                position_size=position_size,
                message_id=message_id
            )
        # 口语化：tsll 在16.02附近开个底仓 常规仓的一半
        match = cls.BUY_PATTERN_4.search(message)
        if match:
            ticker = match.group(1).upper()
            price = float(match.group(2))
            pos = cls.POSITION_SIZE_PATTERN.search(message)
            position_size = pos.group(1) if pos else None
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                price=price,
                position_size=position_size,
                message_id=message_id
            )
        # 15.43加了常规一半的tsll / 15.35加个tsll 常规的一半
        for pattern in (cls.BUY_PATTERN_5, cls.BUY_PATTERN_7):
            match = pattern.search(message)
            if not match:
                continue
            price = float(match.group(1))
            ticker = match.group(2).upper()
            pos = cls.POSITION_SIZE_PATTERN.search(message)
            position_size = pos.group(1) if pos else None
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                price=price,
                position_size=position_size,
                message_id=message_id
            )
        # 15.17附近加回了周五卖出的那部分tsll
        match = cls.BUY_PATTERN_6.search(message)
        if match:
            price = float(match.group(1))
            ticker = match.group(2).upper()
            ref = None
            if cls.BUY_REF_FRIDAY.search(message):
                ref = "周五卖出的"
            elif cls.BUY_REF_TODAY.search(message):
                ref = "今天卖出的"
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                price=price,
                buy_quantity_reference=ref,
                message_id=message_id
            )
        # tsll15.48在吸回卖出的一部分
        match = cls.BUY_PATTERN_8.search(message)
        if match:
            ticker = match.group(1).upper()
            price = float(match.group(2))
            ref = "卖出的一部分" if cls.BUY_REF_PART.search(message) else "今天卖出的"
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                price=price,
                buy_quantity_reference=ref,
                message_id=message_id
            )

        # ===== 新增口语化买入模式 =====

        # 价格区间 + 回吸/低吸: "19.6-19.7附近小仓位回吸一笔" / "19.4-19.5附近吸回"
        match = cls.BUY_RANGE_ABSORB.search(message)
        if match:
            ticker = match.group(1).upper()
            lo, hi = cls._sort_range(float(match.group(2)), float(match.group(3)))
            position_size = cls._resolve_position_size(message)
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                price=cls._round2((lo + hi) / 2),
                price_range=[lo, hi],
                position_size=position_size,
                message_id=message_id
            )

        # "nvdl今天还是转弯时候吸 83-83.5" (action before range)
        match = cls.BUY_TICKER_ACTION_RANGE.search(message)
        if match:
            ticker = match.group(1).upper()
            lo, hi = cls._sort_range(float(match.group(2)), float(match.group(3)))
            position_size = cls._resolve_position_size(message)
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                price=cls._round2((lo + hi) / 2),
                price_range=[lo, hi],
                position_size=position_size,
                message_id=message_id
            )

        # 价格区间 + 在回吸: "15.1-15在回吸今天卖出的部分"
        match = cls.BUY_RANGE_RETRACE.search(message)
        if match:
            ticker = match.group(1).upper()
            lo, hi = cls._sort_range(float(match.group(2)), float(match.group(3)))
            ref = None
            if cls.BUY_REF_TODAY.search(message):
                ref = "今天卖出的"
            elif cls.BUY_REF_FRIDAY.search(message):
                ref = "周五卖出的"
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                price=cls._round2((lo + hi) / 2),
                price_range=[lo, hi],
                buy_quantity_reference=ref,
                message_id=message_id
            )

        # 价格区间 + 建仓/买一半: "21.3-21.4附近建个小仓位" / "21.3-21.4买一半"
        match = cls.BUY_RANGE_BUILD.search(message)
        if match:
            ticker = match.group(1).upper()
            lo, hi = cls._sort_range(float(match.group(2)), float(match.group(3)))
            pos = cls.POSITION_SIZE_PATTERN.search(message)
            # "买一半" 作为 position_size 的一种
            if '一半' in message and not pos:
                position_size = '一半'
            else:
                position_size = pos.group(1) if pos else None
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                price=cls._round2((lo + hi) / 2),
                price_range=[lo, hi],
                position_size=position_size,
                message_id=message_id
            )

        # 回踩+单价+回吸: "回踩15.05回吸" / "回踩20.3时候建点"
        match = cls.BUY_RETRACE.search(message)
        if match:
            ticker = match.group(1).upper()
            price = float(match.group(2))
            ref = None
            if '昨天' in message:
                ref = "昨天卖出的"
            elif cls.BUY_REF_TODAY.search(message):
                ref = "今天卖出的"
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                price=price,
                buy_quantity_reference=ref,
                message_id=message_id
            )

        # 入了仓位: "在18.99附近入了仓位"
        match = cls.BUY_ENTERED.search(message)
        if match:
            ticker = match.group(1).upper()
            price = float(match.group(2))
            position_size = cls._resolve_position_size(message)
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                price=price,
                position_size=position_size,
                message_id=message_id
            )

        # 单价 + 回吸/吸回/低吸: "16.01附近回吸一笔" / "18.8附近回吸一笔" / "14.6低吸"
        match = cls.BUY_ABSORB_SINGLE.search(message)
        if match:
            ticker = match.group(1).upper()
            price = float(match.group(2))
            position_size = cls._resolve_position_size(message)
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                price=price,
                position_size=position_size,
                message_id=message_id
            )

        # 价格直接紧跟回吸: "19.4回吸点" / "14.6回吸常规的一半" / "16.45在吸回"
        match = cls.BUY_PRICE_ABSORB.search(message)
        if match:
            ticker = match.group(1).upper()
            price = float(match.group(2))
            position_size = cls._resolve_position_size(message)
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                price=price,
                position_size=position_size,
                message_id=message_id
            )

        # 挂单在: "可以挂小仓位单在19.2这里"
        match = cls.BUY_HANG_ORDER.search(message)
        if match:
            ticker = match.group(1).upper()
            price = float(match.group(2))
            pos = cls.POSITION_SIZE_PATTERN.search(message)
            position_size = pos.group(1) if pos else '小仓位'
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                price=price,
                position_size=position_size,
                message_id=message_id
            )

        # 挂单的XX的低吸: "后面看挂单的16.64的低吸"
        match = cls.BUY_HANG_ABSORB.search(message)
        if match:
            ticker = match.group(1).upper()
            price = float(match.group(2))
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                price=price,
                position_size='小仓位',
                message_id=message_id
            )

        # 价格附近接: "15。03附近接" (支持中文句号)
        match = cls.BUY_CATCH_PRICE.search(message)
        if match:
            ticker = match.group(1).upper()
            price = cls._normalize_price(match.group(2))
            pos = cls.POSITION_SIZE_PATTERN.search(message)
            position_size = pos.group(1) if pos else None
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                price=price,
                position_size=position_size,
                message_id=message_id
            )

        # price吸回 ticker: "14附近吸回 tsll 卖出那部分"
        match = cls.BUY_PRICE_THEN_TICKER.search(message)
        if match:
            price = float(match.group(1))
            ticker = match.group(2).upper()
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                price=price,
                buy_quantity_reference="卖出的",
                message_id=message_id
            )

        # 附近小加: "18.3附近小加" (小仓位买入)
        match = cls.BUY_SMALL_ADD.search(message)
        if match:
            ticker = match.group(1).upper()
            price = float(match.group(2))
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                price=price,
                position_size='小仓位',
                message_id=message_id
            )

        # 价格 + 附近吸 (价格引用): "tsll 14点12分价格15.98 可以这个价格附近吸"
        match = cls.BUY_PRICE_REF_ABSORB.search(message)
        if match:
            ticker = match.group(1).upper()
            price = float(match.group(2))
            pos = cls.POSITION_SIZE_PATTERN.search(message)
            position_size = pos.group(1) if pos else None
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                price=price,
                position_size=position_size,
                message_id=message_id
            )

        # 开了一笔/建了一笔: "tsll 18.06 开了一笔常规仓的一半"
        match = cls.BUY_OPENED_ONE.search(message)
        if match:
            ticker = match.group(1).upper()
            price = float(match.group(2))
            pos = cls.POSITION_SIZE_PATTERN.search(message)
            position_size = pos.group(1) if pos else None
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                price=price,
                position_size=position_size,
                message_id=message_id
            )

        # 价格区间 + 支撑: "tsll 19.3-19.2 注意下刚打压到支撑了 也是小仓位日内"
        match = cls.BUY_RANGE_SUPPORT.search(message)
        if match:
            ticker = match.group(1).upper()
            lo, hi = cls._sort_range(float(match.group(2)), float(match.group(3)))
            pos = cls.POSITION_SIZE_PATTERN.search(message)
            position_size = pos.group(1) if pos else None
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                price=cls._round2((lo + hi) / 2),
                price_range=[lo, hi],
                position_size=position_size,
                message_id=message_id
            )

        # 回吸在前，价格区间在后: "tsll...回吸...17.8-17.9附近"
        match = cls.BUY_ABSORB_THEN_RANGE.search(message)
        if match:
            ticker = match.group(1).upper()
            lo, hi = cls._sort_range(float(match.group(2)), float(match.group(3)))
            pos = cls.POSITION_SIZE_PATTERN.search(message)
            position_size = pos.group(1) if pos else None
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                price=cls._round2((lo + hi) / 2),
                price_range=[lo, hi],
                position_size=position_size,
                message_id=message_id
            )

        # ticker + price 直接列举 (价格列表买入): "tsll 15.6 rklb 38.3-38.6附近"
        match = cls.BUY_LIST_PRICE.search(message)
        if match:
            ticker = match.group(1).upper()
            price = float(match.group(2))
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                price=price,
                message_id=message_id
            )

        # ===== ticker 在句尾/中间的买入模式 =====

        # "19.2附近在小仓位开仓tsll"
        match = cls.BUY_OPEN_SUFFIX.search(message)
        if match:
            price = cls._normalize_price(match.group(1))
            ticker = match.group(2).upper()
            pos = cls.POSITION_SIZE_PATTERN.search(message)
            position_size = pos.group(1) if pos else '小仓位'
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                price=price,
                position_size=position_size,
                message_id=message_id
            )

        # "19.1-19.15建了点这轮tsll底仓"
        match = cls.BUY_RANGE_BUILD_SUFFIX.search(message)
        if match:
            lo, hi = cls._sort_range(
                cls._normalize_price(match.group(1)),
                cls._normalize_price(match.group(2))
            )
            ticker = match.group(3).upper()
            pos = cls.POSITION_SIZE_PATTERN.search(message)
            position_size = pos.group(1) if pos else None
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                price=cls._round2((lo + hi) / 2),
                price_range=[lo, hi],
                position_size=position_size,
                message_id=message_id
            )

        # "15.40在吸回卖出的tsll"
        match = cls.BUY_ABSORB_BACK_SUFFIX.search(message)
        if match:
            price = cls._normalize_price(match.group(1))
            ticker = match.group(2).upper()
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                price=price,
                message_id=message_id
            )

        # "tsll回吸也是看19.4 可以19.43挂个单子"
        match = cls.BUY_TICKER_ABSORB_HANG.search(message)
        if match:
            ticker = match.group(1).upper()
            price = cls._normalize_price(match.group(2))
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                price=price,
                position_size='小仓位',
                message_id=message_id
            )

        # "盘前回吸了常规一半的tsll在16.38"
        match = cls.BUY_ACTION_TICKER_AT_PRICE.search(message)
        if match:
            ticker = match.group(1).upper()
            price = cls._normalize_price(match.group(2))
            position_size = cls._resolve_position_size(message)
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                price=price,
                position_size=position_size,
                message_id=message_id
            )

        # "尾盘17.97常规仓一半的tsll接回"
        match = cls.BUY_POSITION_TICKER_ACTION.search(message)
        if match:
            price = cls._normalize_price(match.group(1))
            ticker = match.group(2).upper()
            position_size = cls._resolve_position_size(message)
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                price=price,
                position_size=position_size,
                message_id=message_id
            )

        # "17.2附近 吸了tsll" / "14.52盘前加了tsll"
        match = cls.BUY_PRICE_ACTION_SUFFIX.search(message)
        if match:
            price = cls._normalize_price(match.group(1))
            ticker = match.group(2).upper()
            position_size = cls._resolve_position_size(message)
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                price=price,
                position_size=position_size,
                message_id=message_id
            )

        # "14.05加仓了tsll" / "夜盘14.05加仓了tsll"
        match = cls.BUY_PRICE_ADD_POSITION_SUFFIX.search(message)
        if match:
            price = cls._normalize_price(match.group(1))
            ticker = match.group(2).upper()
            position_size = cls._resolve_position_size(message)
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                price=price,
                position_size=position_size,
                message_id=message_id
            )

        # "84.8附近吸点nvdl" / "84附近少量接nvdl" / "82.3附近可以吸回点nvdl底仓"
        match = cls.BUY_APPROX_ACTION_TICKER_SUFFIX.search(message)
        if match:
            price = cls._normalize_price(match.group(1))
            ticker = match.group(2).upper()
            position_size = cls._resolve_position_size(message)
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                price=price,
                position_size=position_size,
                message_id=message_id
            )

        # "夜盘83附近开仓了常规仓一半的nvdl"
        match = cls.BUY_OPEN_POSITION_TICKER_SUFFIX.search(message)
        if match:
            price = cls._normalize_price(match.group(1))
            ticker = match.group(2).upper()
            position_size = cls._resolve_position_size(message)
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                price=price,
                position_size=position_size,
                message_id=message_id
            )

        # "321附近可以加仓mstr" / "6.7附近建仓个新的 bbai" / "3.68附近买回之前卖出的rxrx"
        match = cls.BUY_VERBOSE_ACTION_SUFFIX.search(message)
        if match:
            price = cls._normalize_price(match.group(1))
            ticker = match.group(2).upper()
            position_size = cls._resolve_position_size(message)
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                price=price,
                position_size=position_size,
                message_id=message_id
            )

        return None

    @classmethod
    def _parse_sell(cls, message: str, message_id: str) -> Optional[StockInstruction]:
        # 标准格式
        for pattern in (cls.SELL_PATTERN_1, cls.SELL_PATTERN_2, cls.SELL_PATTERN_3):
            match = pattern.search(message)
            if not match:
                continue
            ticker = match.group(1).upper()
            price = float(match.group(2))
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=price,
                sell_quantity='全部',
                message_id=message_id
            )
        # tsll ... 16.04附近可以出昨天16.02的
        match = cls.SELL_PATTERN_4.search(message)
        if match:
            ticker = match.group(1).upper()
            price = float(match.group(2))
            ref_label = None
            ref_price = None
            ym = cls.SELL_REF_YESTERDAY.search(message)
            if ym:
                ref_price = float(ym.group(1))
                ref_label = f"昨天{ym.group(1)}的"
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=price,
                sell_quantity='全部',
                sell_reference_price=ref_price,
                sell_reference_label=ref_label,
                message_id=message_id
            )
        # 16.4可以出15.43的一半（ticker 可能在句首）
        match = cls.SELL_PATTERN_5.search(message)
        if match:
            ticker = (match.group(1) or "").strip().upper()
            if not ticker:
                ticker = next((m.group(1).upper() for m in re.finditer(r'\b([A-Za-z]{2,5})\b', message) if m.group(1).upper() != "可以"), None)
            if not ticker:
                return None
            price = float(match.group(2))
            ref_price = float(match.group(3))
            half = match.group(4)
            sell_quantity = (half or '全部').strip() if half else '全部'
            if sell_quantity == '一半':
                sell_quantity = '1/2'
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=price,
                sell_quantity=sell_quantity,
                sell_reference_price=ref_price,
                message_id=message_id
            )
        # 15.75出之前15.45剩下一半tsll
        match = cls.SELL_PATTERN_6.search(message)
        if match:
            price = float(match.group(1))
            ref_price = float(match.group(2))
            half = match.group(3)
            ticker = (match.group(4) or "").upper()
            sell_quantity = '1/2' if (half and '半' in str(half)) else '全部'
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=price,
                sell_quantity=sell_quantity,
                sell_reference_price=ref_price,
                sell_reference_label=f"之前{ref_price}",
                message_id=message_id
            )
        # tsll 可以15.3出15.17的
        match = cls.SELL_PATTERN_7.search(message)
        if match:
            ticker = match.group(1).upper()
            price = float(match.group(2))
            ref_price = float(match.group(3))
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=price,
                sell_quantity='全部',
                sell_reference_price=ref_price,
                sell_reference_label=f"{ref_price}的",
                message_id=message_id
            )
        # tsll 在到15.76可以在出15.48那部分
        match = cls.SELL_PATTERN_8.search(message)
        if match:
            ticker = match.group(1).upper()
            price = float(match.group(2))
            ref_price = float(match.group(3))
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=price,
                sell_quantity='全部',
                sell_reference_price=ref_price,
                sell_reference_label=f"{ref_price}那部分",
                message_id=message_id
            )

        # "nvdl今天注意分时转弯时候出84.5那部分"
        match = cls.SELL_TICKER_OUT_PRICE_PART.search(message)
        if match:
            ticker = match.group(1).upper()
            price = float(match.group(2))
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=price,
                sell_quantity='全部',
                sell_reference_price=price,
                sell_reference_label=f"{price}那部分",
                message_id=message_id
            )

        # "nvdl可以86.75 出"
        match = cls.SELL_TICKER_CAN_PRICE_OUT.search(message)
        if match:
            ticker = match.group(1).upper()
            price = float(match.group(2))
            sq = '1/2' if '一半' in message else '全部'
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=price,
                sell_quantity=sq,
                message_id=message_id
            )

        # ===== 新增口语化卖出模式 =====

        # 11. 价格出一半+参考价: "14.31出一半 14吸的" / "15.34出剩下一半14.6吸的"
        match = cls.SELL_HALF_WITH_REF.search(message)
        if match:
            ticker = match.group(1).upper()
            price = float(match.group(2))
            ref_price = float(match.group(3)) if match.group(3) else None
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=price,
                sell_quantity='1/2',
                sell_reference_price=ref_price,
                sell_reference_label=f"{ref_price}吸的" if ref_price else None,
                message_id=message_id
            )

        # 12. "XX时候减掉 YY加仓的": "19时候减掉 18.3加仓的"
        match = cls.SELL_TIME_REDUCE.search(message)
        if match:
            ticker = match.group(1).upper()
            price = float(match.group(2))
            ref_price = float(match.group(3)) if match.group(3) else None
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=price,
                sell_quantity='全部',
                sell_reference_price=ref_price,
                sell_reference_label=f"{ref_price}加仓的" if ref_price else None,
                message_id=message_id
            )

        # 9. 价格区间 + 一半: "19.8-19.9附近出掉剩下一半" / "20-20.1出一半"
        match = cls.SELL_RANGE_HALF.search(message)
        if match:
            ticker = match.group(1).upper()
            lo, hi = cls._sort_range(float(match.group(2)), float(match.group(3)))
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=cls._round2((lo + hi) / 2),
                price_range=[lo, hi],
                sell_quantity='1/2',
                message_id=message_id
            )

        # 10. 单价 + 一半: "19.6附近出一半" / "目前正好到19.6 出掉一半"
        match = cls.SELL_SINGLE_HALF.search(message)
        if match:
            ticker = match.group(1).upper()
            price = float(match.group(2))
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=price,
                sell_quantity='1/2',
                message_id=message_id
            )
        # 10b. "nvdl之前剩下的一半在107.5出"
        match = cls.SELL_HALF_AT_PRICE.search(message)
        if match:
            ticker = match.group(1).upper()
            price = float(match.group(2))
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=price,
                sell_quantity='1/2',
                message_id=message_id
            )
        # 10c. "nvdl上周五剩下点仓位 在盘前90.9附近也出点"
        match = cls.SELL_ALSO_OUT_SOME.search(message)
        if match:
            ticker = match.group(1).upper()
            price = float(match.group(2))
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=price,
                sell_quantity='全部',
                message_id=message_id
            )

        # 13. 价格区间 + 分批出/减点
        match = cls.SELL_RANGE_PARTIAL.search(message)
        if match:
            ticker = match.group(1).upper()
            lo, hi = cls._sort_range(float(match.group(2)), float(match.group(3)))
            # 分批出 = 卖出一半；减点 = 小仓位（常规仓）
            sq = '1/2' if '分批出' in message else '小仓位'
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=cls._round2((lo + hi) / 2),
                price_range=[lo, hi],
                sell_quantity=sq,
                message_id=message_id
            )

        # 14. 价格区间 + 出/减 (通用)
        match = cls.SELL_RANGE_FULL.search(message)
        if match:
            ticker = match.group(1).upper()
            lo, hi = cls._sort_range(float(match.group(2)), float(match.group(3)))
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=cls._round2((lo + hi) / 2),
                price_range=[lo, hi],
                sell_quantity='全部',
                message_id=message_id
            )

        # 18. "XX-YY之间出": "19.6-19.8之间 出"
        match = cls.SELL_RANGE_BETWEEN.search(message)
        if match:
            ticker = match.group(1).upper()
            lo, hi = cls._sort_range(float(match.group(2)), float(match.group(3)))
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=cls._round2((lo + hi) / 2),
                price_range=[lo, hi],
                sell_quantity='全部',
                message_id=message_id
            )

        # 16b. ticker + price + 附近卖出: "oklo盘前冲高94附近卖出"
        match = cls.SELL_PRICE_SELL_OUT.search(message)
        if match:
            ticker = match.group(1).upper()
            price = float(match.group(2))
            sq = '1/2' if '一半' in message else '全部'
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=price,
                sell_quantity=sq,
                message_id=message_id
            )

        # 15. 单价 + 减点/分批出
        match = cls.SELL_PARTIAL.search(message)
        if match:
            ticker = match.group(1).upper()
            price = float(match.group(2))
            # 分批出 = 卖出一半；减点 = 小仓位（常规仓）
            sq = '1/2' if '分批出' in message else '小仓位'
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=price,
                sell_quantity=sq,
                message_id=message_id
            )

        # 16. 单价 + 减 (视为小仓位减出)
        match = cls.SELL_REDUCE.search(message)
        if match:
            ticker = match.group(1).upper()
            price = float(match.group(2))
            ref_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:回吸的|买的|吸的|加仓的)', message)
            ref_price = float(ref_match.group(1)) if ref_match else None
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=price,
                sell_quantity='小仓位',
                sell_reference_price=ref_price,
                sell_reference_label=f"{ref_price}买的" if ref_price else None,
                message_id=message_id
            )

        # 17. 短线出: "18.45出短线"
        match = cls.SELL_SHORT_TERM.search(message)
        if match:
            ticker = match.group(1).upper()
            price = float(match.group(2))
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=price,
                sell_quantity='全部',
                message_id=message_id
            )

        # 19a. 附近出+参考价+的一半: "15.39附近出 15.05的一半"
        match = cls.SELL_APPROX_OUT_REF_HALF.search(message)
        if match:
            ticker = match.group(1).upper()
            price = cls._normalize_price(match.group(2))
            ref_price = cls._normalize_price(match.group(3)) if match.group(3) else None
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=price,
                sell_quantity='1/2',
                sell_reference_price=ref_price,
                sell_reference_label=f"{ref_price}买的" if ref_price else None,
                message_id=message_id
            )

        # 19. 附近出+参考价: "17.45附近出17.35买的"
        match = cls.SELL_APPROX_OUT_REF.search(message)
        if match:
            ticker = match.group(1).upper()
            price = float(match.group(2))
            ref_price = float(match.group(3)) if match.group(3) else None
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=price,
                sell_quantity='全部',
                sell_reference_price=ref_price,
                sell_reference_label=f"{ref_price}买的" if ref_price else None,
                message_id=message_id
            )

        # 22. 出之前/出+参考价: "16.55出之前16.05吸的" / "17.45出17.35买的"
        match = cls.SELL_OUT_BEFORE_REF.search(message)
        if match:
            ticker = match.group(1).upper()
            price = float(match.group(2))
            ref_price = float(match.group(3))
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=price,
                sell_quantity='全部',
                sell_reference_price=ref_price,
                sell_reference_label=f"{ref_price}吸的",
                message_id=message_id
            )

        # 20. 把XX买的出了: "17.77附近也把节前17.98买的出了"
        match = cls.SELL_PUT_OUT_REF.search(message)
        if match:
            ticker = match.group(1).upper()
            price = float(match.group(2))
            ref_price = float(match.group(3)) if match.group(3) else None
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=price,
                sell_quantity='全部',
                sell_reference_price=ref_price,
                sell_reference_label=f"{ref_price}买的" if ref_price else None,
                message_id=message_id
            )

        # 21. 简单附近出: "19.45附近 出"
        match = cls.SELL_APPROX_SIMPLE.search(message)
        if match:
            ticker = match.group(1).upper()
            price = float(match.group(2))
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=price,
                sell_quantity='全部',
                message_id=message_id
            )

        # 23. XX那部分...出: "tsll 19.1 那部分到转弯时候也出"
        match = cls.SELL_THAT_PART.search(message)
        if match:
            ticker = match.group(1).upper()
            ref_price = float(match.group(2))
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=ref_price,
                sell_quantity='全部',
                sell_reference_price=ref_price,
                sell_reference_label=f"{ref_price}那部分",
                message_id=message_id
            )

        # 24. 出昨天/之前XX买的那部分: "出昨天15.04买的那部分"
        match = cls.SELL_YESTERDAY_BUY_PART.search(message)
        if match:
            ticker = match.group(1).upper()
            ref_price = float(match.group(2))
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=ref_price,
                sell_quantity='全部',
                sell_reference_price=ref_price,
                sell_reference_label=f"昨天{ref_price}买的",
                message_id=message_id
            )

        # ===== ticker 在句尾/中间的卖出模式 =====

        # "11.65-11.7附近出11.16的eose剩下一半" (价格区间+附近出+参考价+的+ticker)
        match = cls.SELL_RANGE_OUT_REF_SUFFIX.search(message)
        if match:
            lo, hi = cls._sort_range(
                cls._normalize_price(match.group(1)),
                cls._normalize_price(match.group(2))
            )
            ref_price = cls._normalize_price(match.group(3))
            ticker = match.group(4).upper()
            sq = '1/2' if '一半' in message else '全部'
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=cls._round2((lo + hi) / 2),
                price_range=[lo, hi],
                sell_quantity=sq,
                sell_reference_price=ref_price,
                sell_reference_label=f"{ref_price}的",
                message_id=message_id
            )

        # "19.4出一半18.8的tsll" (价格+出一半+参考买入价+的+ticker)
        match = cls.SELL_HALF_REF_SUFFIX.search(message)
        if match:
            price = cls._normalize_price(match.group(1))
            ref_price = cls._normalize_price(match.group(2))
            ticker = match.group(3).upper()
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=price,
                sell_quantity='1/2',
                sell_reference_price=ref_price,
                sell_reference_label=f"{ref_price}买的",
                message_id=message_id
            )

        # "41.5出夜盘 39.5的iren" (单价+出+中间内容+参考价+的+ticker 句尾)
        match = cls.SELL_PRICE_OUT_REF_SUFFIX.search(message)
        if match:
            price = cls._normalize_price(match.group(1))
            ref_price = cls._normalize_price(match.group(2))
            ticker = match.group(3).upper()
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=price,
                sell_quantity='全部',
                sell_reference_price=ref_price,
                sell_reference_label=f"{ref_price}的",
                message_id=message_id
            )

        # "20.6到20.9这段分批出昨天20。5的tsll" (分批出+参考价+ticker)
        match = cls.SELL_BATCH_REF_SUFFIX.search(message)
        if match:
            lo, hi = cls._sort_range(
                cls._normalize_price(match.group(1)),
                cls._normalize_price(match.group(2))
            )
            ref_price = cls._normalize_price(match.group(3)) if match.group(3) else None
            ticker = match.group(4).upper()
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=cls._round2((lo + hi) / 2),
                price_range=[lo, hi],
                sell_quantity='1/2',
                sell_reference_price=ref_price,
                sell_reference_label=f"昨天{ref_price}的" if ref_price else None,
                message_id=message_id
            )

        # "21.2-21.4之间减仓tsll" / "20.5-20.6附近可以减点剩下的tsll"
        match = cls.SELL_RANGE_REDUCE_SUFFIX.search(message)
        if match:
            lo, hi = cls._sort_range(
                cls._normalize_price(match.group(1)),
                cls._normalize_price(match.group(2))
            )
            ticker = match.group(3).upper()
            sq = '1/2' if '一半' in message else '小仓位'
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=cls._round2((lo + hi) / 2),
                price_range=[lo, hi],
                sell_quantity=sq,
                message_id=message_id
            )

        # "19.7到19.8出 tsll" / "16出tsll"
        match = cls.SELL_PRICE_OUT_SUFFIX.search(message)
        if match:
            p1 = cls._normalize_price(match.group(1))
            p2_str = match.group(2)
            ticker = match.group(3).upper()
            if p2_str:
                lo, hi = cls._sort_range(p1, cls._normalize_price(p2_str))
                price = cls._round2((lo + hi) / 2)
                price_range = [lo, hi]
            else:
                price = p1
                price_range = None
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=price,
                price_range=price_range,
                sell_quantity='全部',
                message_id=message_id
            )

        # "41.5出夜盘 39.5的iren" / "20.32出19.8那部分tsll" / "16.93再出 16.45低吸的tsll"
        match = cls.SELL_PRICE_OUT_REF_SUFFIX.search(message)
        if match:
            price = cls._normalize_price(match.group(1))
            ref_price = cls._normalize_price(match.group(2))
            ticker = match.group(3).upper()
            sq = '1/2' if '一半' in message else '全部'
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=price,
                sell_quantity=sq,
                sell_reference_price=ref_price,
                sell_reference_label=f"{ref_price}的",
                message_id=message_id
            )

        # "17附近减一半16.64挂单进的tsll" / "17.88减一半17.4附近的tsll"
        match = cls.SELL_REDUCE_HALF_REF_SUFFIX.search(message)
        if match:
            price = cls._normalize_price(match.group(1))
            ref_price = cls._normalize_price(match.group(2))
            ticker = match.group(3).upper()
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=price,
                sell_quantity='1/2',
                sell_reference_price=ref_price,
                sell_reference_label=f"{ref_price}的",
                message_id=message_id
            )

        # "21.7也减仓点tsll" / "22附近也可以减点tsll" / "16附近减仓周五加仓的tsll"
        match = cls.SELL_SINGLE_REDUCE_SUFFIX.search(message)
        if match:
            price = cls._normalize_price(match.group(1))
            ticker = match.group(2).upper()
            sq = '1/2' if '一半' in message else '全部'
            ref_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:附近)?(?:买的|吸的|加仓的|加的)', message)
            ref_price = float(ref_match.group(1)) if ref_match else None
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=price,
                sell_quantity=sq,
                sell_reference_price=ref_price,
                sell_reference_label=f"{ref_price}买的" if ref_price else None,
                message_id=message_id
            )

        # "86出一半nvdl" / "94.3出一半nvdl"
        match = cls.SELL_OUT_HALF_NO_REF_SUFFIX.search(message)
        if match:
            price = cls._normalize_price(match.group(1))
            ticker = match.group(2).upper()
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=price,
                sell_quantity='1/2',
                message_id=message_id
            )

        # "43.1出夜盘补的iren那部分" / "75.1出日内买的rklb" / "32.6出个三分之一bmnr"
        match = cls.SELL_PRICE_OUT_GAP_TICKER_SUFFIX.search(message)
        if match:
            price = cls._normalize_price(match.group(1))
            ticker = match.group(2).upper()
            sq = '1/2' if '一半' in message else ('1/3' if '三分之一' in message else '全部')
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=price,
                sell_quantity=sq,
                message_id=message_id
            )

        # "92附近出之前的nvdl底仓" / "76.4附近出盘前买的nvdl" / "81.3近出昨天79.5的nvdl一半"
        match = cls.SELL_APPROX_OUT_TICKER_SUFFIX.search(message)
        if match:
            price = cls._normalize_price(match.group(1))
            ticker = match.group(2).upper()
            sq = '1/2' if '一半' in message else '全部'
            ref_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:的|买的|吸的|加的|低吸的)', message)
            ref_price = cls._normalize_price(ref_match.group(1)) if ref_match and ref_match.group(1) != match.group(1) else None
            return StockInstruction(
                raw_message=message,
                instruction_type=InstructionType.SELL.value,
                ticker=ticker,
                price=price,
                sell_quantity=sq,
                sell_reference_price=ref_price,
                sell_reference_label=f"{ref_price}的" if ref_price else None,
                message_id=message_id
            )

        return None

    @classmethod
    def _parse_stop_loss(cls, message: str, message_id: str) -> Optional[StockInstruction]:
        match = cls.STOCK_STOP_LOSS_PATTERN.search(message)
        if not match:
            return None
        ticker = match.group(1) or match.group(2)
        if not ticker:
            return None  # 无 ticker 时让给关注列表 fallback
        price = float(match.group(3))
        return StockInstruction(
            raw_message=message,
            instruction_type=InstructionType.MODIFY.value,
            ticker=ticker.upper(),
            stop_loss_price=price,
            message_id=message_id
        )

    @classmethod
    def _parse_take_profit(cls, message: str, message_id: str) -> Optional[StockInstruction]:
        match = cls.STOCK_TAKE_PROFIT_PATTERN.search(message)
        if not match:
            return None
        ticker = match.group(1) or match.group(2)
        if not ticker:
            return None  # 无 ticker 时让给关注列表 fallback
        price = float(match.group(3))
        portion_raw = match.group(4) if len(match.groups()) >= 4 and match.group(4) else '全部'
        portion = cls.PORTION_MAP.get(portion_raw, portion_raw)
        return StockInstruction(
            raw_message=message,
            instruction_type=InstructionType.SELL.value,
            ticker=ticker.upper(),
            price=price,
            sell_quantity=portion,
            message_id=message_id
        )

    @classmethod
    def parse_multi_line(cls, text: str) -> list:
        instructions = []
        for line in text.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            instruction = cls.parse(line)
            if instruction:
                instructions.append(instruction)
        return instructions


if __name__ == "__main__":
    test_messages = [
        "AAPL 买入 $150",
        "买入 TSLA 在 $250",
        "NVDA $900 买",
        "AAPL 卖出 $180",
        "卖出 TSLA 在 $300",
        "NVDA $950 出",
        "AAPL 止损 $145",
        "止损 TSLA 在 $240",
        "AAPL 止盈 $200",
        "止盈 TSLA 在 $350 出一半",
    ]
    print("=" * 60)
    print("正股指令解析测试")
    print("=" * 60)
    for msg in test_messages:
        print(f"\n原始消息: {msg}")
        instruction = StockParser.parse(msg)
        if instruction:
            print(f"解析结果: {instruction}")
            print(f"JSON: {instruction.to_json()}")
        else:
            print("解析结果: 未能识别")
