"""
配置模块 - 管理凭据和应用设置
"""
import json
import os
from dotenv import load_dotenv
from typing import List, Optional, Tuple

# 加载 .env 文件
load_dotenv()


def _read_pages_raw() -> str:
    """读取 PAGES 原始字符串，支持 .env 中多行 JSON（dotenv 多行会截断）。"""
    raw = os.getenv("PAGES", "").strip()
    # 若从环境变量得到的是完整 JSON（以 [ 开头且能解析），直接使用
    if raw.startswith("[") and raw.endswith("]"):
        return raw
    # 否则尝试从 .env 文件读取多行值（dotenv 对未引号的多行只取第一行）
    for env_path in (".env", os.path.join(os.path.dirname(__file__), ".env")):
        if not os.path.isfile(env_path):
            continue
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError:
            continue
        start = content.find("PAGES=")
        if start == -1:
            continue
        start += len("PAGES=")
        # 跳过等号后的换行/空格
        while start < len(content) and content[start] in " \t\r\n":
            start += 1
        if start >= len(content):
            continue
        # 从 [ 开始收集到匹配的 ]
        if content[start] != "[":
            continue
        depth = 0
        end = start
        for i in range(start, len(content)):
            c = content[i]
            if c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if depth == 0 and end > start:
            return content[start:end].strip()
    return raw or "[]"


def _parse_pages_env() -> List[Tuple[str, str, str]]:
    """从环境变量 PAGES 解析 JSON 数组，返回 [(url, type, name), ...]，type 为 'option' 或 'stock'，name 为可选说明。"""
    raw = _read_pages_raw()
    if not raw or raw == "[]":
        return []
    try:
        arr = json.loads(raw)
    except json.JSONDecodeError:
        return []
    result = []
    for item in arr:
        if not isinstance(item, dict):
            continue
        url = (item.get("url") or "").strip()
        t = (item.get("type") or "").strip().lower()
        if t == "options":
            t = "option"
        if not url or t not in ("option", "stock"):
            continue
        name = (item.get("name") or "").strip()
        result.append((url, t, name))
    return result


class Config:
    """应用配置"""
    
    # Whop 登录凭据
    WHOP_EMAIL: str = os.getenv("WHOP_EMAIL", "")
    WHOP_PASSWORD: str = os.getenv("WHOP_PASSWORD", "")
    
    # 监控页面配置：PAGES 为 JSON 数组 [{"url":"...","type":"option|stock","name":"说明"}, ...]，启动时选择其中一个监控
    _PAGES: List[Tuple[str, str, str]] = _parse_pages_env()
    
    # Whop 登录页面
    LOGIN_URL: str = os.getenv(
        "LOGIN_URL",
        "https://whop.com/login/"
    )
    
    # 浏览器设置
    HEADLESS: bool = os.getenv("HEADLESS", "false").lower() == "true"
    SLOW_MO: int = int(os.getenv("SLOW_MO", "0"))  # 毫秒，用于调试
    
    # 监控设置
    MONITOR_MODE: str = os.getenv("MONITOR_MODE", "event")  # 监控模式: event/poll
    POLL_INTERVAL: float = float(os.getenv("POLL_INTERVAL", "2.0"))  # 轮询间隔（秒）
    CHECK_INTERVAL: float = float(os.getenv("CHECK_INTERVAL", "0.5"))  # 事件驱动模式检查间隔（秒）
    STATUS_REPORT_INTERVAL: int = int(os.getenv("STATUS_REPORT_INTERVAL", "60"))  # 状态报告间隔（秒）
    
    # Cookie 持久化路径
    STORAGE_STATE_PATH: str = os.getenv("STORAGE_STATE_PATH", "storage_state.json")
    
    # 输出设置
    OUTPUT_FILE: str = os.getenv("OUTPUT_FILE", "output/signals.json")
    
    # 消息展示模式
    DISPLAY_MODE: str = os.getenv("DISPLAY_MODE", "both")  # raw, parsed, both
    
    # 是否跳过首次连接时的历史消息（仅处理连接后新产生的消息）
    SKIP_INITIAL_MESSAGES: bool = os.getenv("SKIP_INITIAL_MESSAGES", "false").lower() in ("true", "1", "yes")
    
    # 消息过滤配置
    FILTER_AUTHORS: List[str] = [
        author.strip() 
        for author in os.getenv("FILTER_AUTHORS", "").split(",") 
        if author.strip()
    ]
    
    # 日志配置
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")  # DEBUG, INFO, WARNING, ERROR
    
    # 存储路径配置
    POSITION_FILE: str = os.getenv("POSITION_FILE", "data/positions.json")
    LOG_DIR: str = os.getenv("LOG_DIR", "logs")
    
    # 保留 TARGET_URL 作为向后兼容属性
    @property
    def TARGET_URL(self) -> str:
        """向后兼容：返回第一个监控页面 URL"""
        return self._PAGES[0][0] if self._PAGES else ""
    
    @classmethod
    def validate(cls) -> bool:
        """验证必需的配置项"""
        if not cls._PAGES:
            print("错误: 请在 .env 中配置 PAGES（JSON 数组），至少一项，如:")
            print('  PAGES=[{"url":"https://whop.com/.../app/","type":"option"}]')
            return False
        
        # 验证展示模式
        if cls.DISPLAY_MODE not in ['raw', 'parsed', 'both']:
            print(f"警告: 无效的 DISPLAY_MODE '{cls.DISPLAY_MODE}'，使用默认值 'both'")
            cls.DISPLAY_MODE = 'both'
        
        return True
    
    @classmethod
    def get_all_pages(cls) -> List[Tuple[str, str, str]]:
        """
        获取 PAGES 中所有页面配置（供启动时选择其一监控）。
        
        Returns:
            [(url, page_type, name), ...]，page_type 为 'option' 或 'stock'，name 为可选说明
        """
        return list(cls._PAGES)

    def generate():
        """创建 .env.example 模板文件"""
        env_example_path = ".env.example"
        if not os.path.exists(env_example_path):
            with open(env_example_path, "w", encoding="utf-8") as f:
                f.write(ENV_TEMPLATE)
            print(f"已创建配置模板: {env_example_path}")
            print("请复制为 .env 并填写你的凭据")

    @classmethod
    def load(cls) -> Optional[Tuple[str, str, str]]:
        """
        解析 PAGES 配置并让用户选择本次要监控的一个页面。
        返回 (url, type, name)，失败或取消时返回 None。
        """
        page_configs = cls.get_all_pages()
        if not page_configs:
            print("❌ 未配置 PAGES 或解析失败，请在 .env 中配置 PAGES（JSON 数组）")
            return None

        if not cls.validate():
            Config.generate()
            return None

        selected: Optional[Tuple[str, str, str]] = None
        if len(page_configs) == 1:
            selected = page_configs[0]
            url, ptype, name = selected
            desc = f"{name} - " if name else ""
            print(f"📌 当前仅配置一个页面，将监控: [{ptype.upper()}] {desc}{url}\n")
        else:
            print("请选择本次要监控的页面（每次运行仅监控一个）:\n")
            for i, (url, ptype, name) in enumerate(page_configs, 1):
                label = "期权" if ptype == "option" else "正股"
                desc = f"{name} - " if name else ""
                print(f"  {i}. [{label}] {desc}{url}")
            print()
            while True:
                choice = input(f"请输入序号 (1-{len(page_configs)}): ").strip()
                idx = int(choice)
                if 1 <= idx <= len(page_configs):
                    selected = page_configs[idx - 1]
                    break
                else:
                    print("无效输入，请重新输入序号。")
            if selected:
                url, ptype, name = selected
                desc = f"{name} - " if name else ""
                print(f"\n✅ 已选择: [{ptype.upper()}] {desc}{url}\n")
                return selected
        return None


# 创建示例 .env 文件模板
ENV_TEMPLATE = """# ============================================================
# Whop 配置
# ============================================================

# 登录凭据
WHOP_EMAIL=your_email@example.com
WHOP_PASSWORD=your_password

# 监控页面（JSON 数组，启动时选择其一监控）。type: option=期权, stock=正股
# PAGES=[{"url":"https://whop.com/.../app/","type":"option"},{"url":"https://whop.com/.../app/","type":"stock"}]
# LOGIN_URL=https://whop.com/login/

# 浏览器设置
HEADLESS=false  # 是否无头模式运行
SLOW_MO=0       # 浏览器操作延迟（毫秒），用于调试

# 监控设置
POLL_INTERVAL=2.0  # 轮询间隔（秒）

# Cookie 持久化路径
# STORAGE_STATE_PATH=storage_state.json

# 输出设置
# OUTPUT_FILE=output/signals.json

# 监控消息：是否跳过首次连接时的历史消息（true=只处理连接后新消息，false=首次也处理当前页消息）
# SKIP_INITIAL_MESSAGES=false

# 消息过滤设置
# FILTER_AUTHORS=xiaozhaolucky  # 只处理指定作者的消息，多个作者用逗号分隔

# ============================================================
# 长桥 OpenAPI 配置
# ============================================================

# 账户模式切换：paper（模拟账户）/ real（真实账户）
LONGPORT_MODE=paper

# 模拟账户配置（用于测试，不会真实交易）
LONGPORT_PAPER_APP_KEY=your_paper_app_key
LONGPORT_PAPER_APP_SECRET=your_paper_app_secret
LONGPORT_PAPER_ACCESS_TOKEN=your_paper_access_token

# 真实账户配置（实盘交易，请谨慎使用）
LONGPORT_REAL_APP_KEY=your_real_app_key
LONGPORT_REAL_APP_SECRET=your_real_app_secret
LONGPORT_REAL_ACCESS_TOKEN=your_real_access_token

# 通用配置
LONGPORT_REGION=cn  # cn=中国大陆，hk=香港（推荐中国大陆用户使用 cn）
LONGPORT_ENABLE_OVERNIGHT=false  # 是否开启夜盘行情

# 交易设置
LONGPORT_AUTO_TRADE=false  # 是否启用自动交易（true=自动下单，false=仅监控）
LONGPORT_DRY_RUN=true  # 是否启用模拟模式（true=不实际下单，仅打印日志）

# 期权默认止损（true=每次期权买入成交后按比例设止损，否则仅根据监听到的止损消息设置）
ENABLE_DEFAULT_STOP_LOSS=false
DEFAULT_STOP_LOSS_RATIO=38  # 止损比例%，38 表示价格跌到买入价的 62% 时止损
"""


