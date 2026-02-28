"""
正股指令解析器
解析正股买卖交易信号
"""
import re
import hashlib
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Tuple
from models.instruction import InstructionType
from models.stock_instruction import StockInstruction


class StockParser:
    """正股指令解析器"""

    BUY_PATTERN_1 = re.compile(
        r'([A-Z]{2,5})\s+(?:买入|买)\s+\$?(\d+(?:\.\d+)?)',
        re.IGNORECASE
    )
    BUY_PATTERN_2 = re.compile(
        r'(?:买入|买|建仓)\s+([A-Z]{2,5})\s+(?:在|价格)?\s*\$?(\d+(?:\.\d+)?)',
        re.IGNORECASE
    )
    BUY_PATTERN_3 = re.compile(
        r'([A-Z]{2,5})\s+\$?(\d+(?:\.\d+)?)\s+(?:买入|买)',
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

    # 口语化买入：tsll 在16.02附近开个底仓 / 15.43加了常规一半的tsll / 15.35加个tsll / tsll15.48在吸回
    BUY_PATTERN_4 = re.compile(
        r'([A-Za-z]{2,5})\s+在\s*(\d+(?:\.\d+)?)\s*附近\s*(?:开个?底仓|开底仓|加仓|加)',
        re.IGNORECASE
    )
    BUY_PATTERN_5 = re.compile(
        r'(\d+(?:\.\d+)?)\s*(?:加|加了)(?:了)?[^A-Za-z]*([A-Za-z]{2,5})\b',
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
    # 17. 短线出: "18.45出短线"
    SELL_SHORT_TERM = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,30}?(\d+(?:\.\d+)?)\s*出短线',
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
    # 21. 简单附近出: "19.45附近 出" / "19.1那部分转弯在19.45附近 出" (需要附近 紧跟 出)
    SELL_APPROX_SIMPLE = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,60}?(\d+(?:\.\d+)?)\s*附近\s*出(?:\s|$|了|掉)',
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
        r'([A-Za-z]{2,5})[\s\S]{0,60}?(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)\s*(?:附近)?\s*[\s\S]{0,15}?(?:支撑)?(?:分批)?(?:回吸|吸回|低吸|吸一笔)',
        re.IGNORECASE
    )
    # 10. 价格区间 + 在回吸/回吸: "15.1-15在回吸今天卖出的部分"
    BUY_RANGE_RETRACE = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,40}?(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)\s*(?:在)?(?:回吸|吸回)',
        re.IGNORECASE
    )
    # 11. 价格区间 + 建仓/买一半/加一笔
    BUY_RANGE_BUILD = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,60}?(?:在\s*)?(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)\s*(?:附近)?\s*(?:建个?小仓位|建底仓|建仓|加一笔|买一半|买)',
        re.IGNORECASE
    )
    # 12. 回踩+单价+回吸: "回踩15.05回吸" / "回踩20.3时候建点"
    BUY_RETRACE = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,30}?回踩\s*(\d+(?:\.\d+)?)\s*(?:回吸|建点|时候建点|低吸)',
        re.IGNORECASE
    )
    # 13. 单价 + 回吸/吸回/低吸 (包含"在"前缀和"一笔"后缀变体)
    BUY_ABSORB_SINGLE = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,50}?(\d+(?:\.\d+)?)\s*(?:附近)?\s*(?:在\s*)?(?:回吸|吸回|低吸)(?:一笔|点)?',
        re.IGNORECASE
    )
    # 13b. "XX回吸" (价格直接紧跟回吸/吸回): "19.4回吸点" / "14.6回吸常规的一半"
    BUY_PRICE_ABSORB = re.compile(
        r'([A-Za-z]{2,5})[\s\S]{0,30}?(\d+(?:\.\d+)?)\s*(?:在)?\s*(?:回吸|吸回)(?!\s*之前)',
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

    # ===== ticker 在句尾/句中 的卖出模式 =====
    # 卖出 T1: "21.2-21.4之间减仓tsll" / "20.5-20.6附近可以减点剩下的tsll"
    SELL_RANGE_REDUCE_SUFFIX = re.compile(
        r'(\d+(?:[.。]\d+)?)\s*[-~到]\s*(\d+(?:[.。]\d+)?)\s*(?:附近|之间|这段)?\s*[\s\S]{0,15}?(?:减仓|减点|减掉|出)\s*[\s\S]{0,15}?([A-Za-z]{2,5})(?![a-zA-Z0-9])',
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

        return None

    @classmethod
    def _parse_stop_loss(cls, message: str, message_id: str) -> Optional[StockInstruction]:
        match = cls.STOCK_STOP_LOSS_PATTERN.search(message)
        if not match:
            return None
        ticker = match.group(1) or match.group(2)
        price = float(match.group(3))
        return StockInstruction(
            raw_message=message,
            instruction_type=InstructionType.MODIFY.value,
            ticker=ticker.upper() if ticker else None,
            stop_loss_price=price,
            message_id=message_id
        )

    @classmethod
    def _parse_take_profit(cls, message: str, message_id: str) -> Optional[StockInstruction]:
        match = cls.STOCK_TAKE_PROFIT_PATTERN.search(message)
        if not match:
            return None
        ticker = match.group(1) or match.group(2)
        price = float(match.group(3))
        portion_raw = match.group(4) if len(match.groups()) >= 4 and match.group(4) else '全部'
        portion = cls.PORTION_MAP.get(portion_raw, portion_raw)
        return StockInstruction(
            raw_message=message,
            instruction_type=InstructionType.SELL.value,
            ticker=ticker.upper() if ticker else None,
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
