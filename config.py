"""
配置模块 - 管理凭据和应用设置
"""
import os
from dotenv import load_dotenv
from typing import List

# 加载 .env 文件
load_dotenv()


class Config:
    """应用配置"""
    
    # Whop 登录凭据
    WHOP_EMAIL: str = os.getenv("WHOP_EMAIL", "")
    WHOP_PASSWORD: str = os.getenv("WHOP_PASSWORD", "")
    
    # 多页面 URL 配置
    WHOP_OPTION_PAGES: List[str] = [
        url.strip() 
        for url in os.getenv("WHOP_OPTION_PAGES", "").split(",") 
        if url.strip()
    ]
    WHOP_STOCK_PAGES: List[str] = [
        url.strip() 
        for url in os.getenv("WHOP_STOCK_PAGES", "").split(",") 
        if url.strip()
    ]
    
    # 兼容旧配置：如果没有设置新的多页面配置，使用旧的 TARGET_URL
    if not WHOP_OPTION_PAGES:
        _target_url = os.getenv(
            "TARGET_URL",
            "https://whop.com/joined/stock-and-option/-9vfxZgBNgXykNt/app/"
        )
        if _target_url:
            WHOP_OPTION_PAGES = [_target_url]
    
    # 页面类型启用控制
    ENABLE_OPTION_MONITOR: bool = os.getenv("ENABLE_OPTION_MONITOR", "true").lower() == "true"
    ENABLE_STOCK_MONITOR: bool = os.getenv("ENABLE_STOCK_MONITOR", "false").lower() == "true"
    
    # Whop 登录页面
    LOGIN_URL: str = os.getenv(
        "LOGIN_URL",
        "https://whop.com/login/"
    )
    
    # 浏览器设置
    HEADLESS: bool = os.getenv("HEADLESS", "false").lower() == "true"
    SLOW_MO: int = int(os.getenv("SLOW_MO", "0"))  # 毫秒，用于调试
    
    # 监控设置
    POLL_INTERVAL: float = float(os.getenv("POLL_INTERVAL", "2.0"))  # 轮询间隔（秒）
    
    # Cookie 持久化路径
    STORAGE_STATE_PATH: str = os.getenv("STORAGE_STATE_PATH", "storage_state.json")
    
    # 输出设置
    OUTPUT_FILE: str = os.getenv("OUTPUT_FILE", "output/signals.json")
    
    # 消息展示模式
    DISPLAY_MODE: str = os.getenv("DISPLAY_MODE", "both")  # raw, parsed, both
    
    # 日志配置
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")  # DEBUG, INFO, WARNING, ERROR
    
    # 样本和数据集配置
    ENABLE_SAMPLE_COLLECTION: bool = os.getenv("ENABLE_SAMPLE_COLLECTION", "true").lower() == "true"
    SAMPLE_DATA_DIR: str = os.getenv("SAMPLE_DATA_DIR", "samples/data")
    
    # 存储路径配置
    POSITION_FILE: str = os.getenv("POSITION_FILE", "data/positions.json")
    LOG_DIR: str = os.getenv("LOG_DIR", "logs")
    
    # 保留 TARGET_URL 作为向后兼容属性
    @property
    def TARGET_URL(self) -> str:
        """向后兼容：返回第一个期权页面URL"""
        return self.WHOP_OPTION_PAGES[0] if self.WHOP_OPTION_PAGES else ""
    
    @classmethod
    def validate(cls) -> bool:
        """验证必需的配置项"""
        if not cls.WHOP_EMAIL or not cls.WHOP_PASSWORD:
            print("错误: 请设置 WHOP_EMAIL 和 WHOP_PASSWORD 环境变量")
            print("可以在 .env 文件中设置，或直接设置环境变量")
            return False
        
        # 验证至少启用了一种监控类型
        if not cls.ENABLE_OPTION_MONITOR and not cls.ENABLE_STOCK_MONITOR:
            print("警告: 未启用任何监控类型（期权和正股都未启用）")
            print("请在 .env 中设置 ENABLE_OPTION_MONITOR=true 或 ENABLE_STOCK_MONITOR=true")
            return False
        
        # 验证相应的页面URL已配置
        if cls.ENABLE_OPTION_MONITOR and not cls.WHOP_OPTION_PAGES:
            print("错误: 启用了期权监控但未配置 WHOP_OPTION_PAGES")
            return False
        
        if cls.ENABLE_STOCK_MONITOR and not cls.WHOP_STOCK_PAGES:
            print("错误: 启用了正股监控但未配置 WHOP_STOCK_PAGES")
            return False
        
        # 验证展示模式
        if cls.DISPLAY_MODE not in ['raw', 'parsed', 'both']:
            print(f"警告: 无效的 DISPLAY_MODE '{cls.DISPLAY_MODE}'，使用默认值 'both'")
            cls.DISPLAY_MODE = 'both'
        
        return True
    
    @classmethod
    def get_all_pages(cls) -> List[tuple]:
        """
        获取所有需要监控的页面配置
        
        Returns:
            [(url, page_type), ...] 列表，page_type 为 'option' 或 'stock'
        """
        pages = []
        if cls.ENABLE_OPTION_MONITOR:
            pages.extend([(url, 'option') for url in cls.WHOP_OPTION_PAGES])
        if cls.ENABLE_STOCK_MONITOR:
            pages.extend([(url, 'stock') for url in cls.WHOP_STOCK_PAGES])
        return pages


# 创建示例 .env 文件模板
ENV_TEMPLATE = """# ============================================================
# Whop 配置
# ============================================================

# 登录凭据
WHOP_EMAIL=your_email@example.com
WHOP_PASSWORD=your_password

# 页面 URL（可选，有默认值）
# TARGET_URL=https://whop.com/joined/stock-and-option/-9vfxZgBNgXykNt/app/
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

# 风险控制配置
LONGPORT_MAX_POSITION_RATIO=0.20  # 单个持仓不超过账户资金的 20%
LONGPORT_MAX_DAILY_LOSS=0.05  # 单日最大亏损 5%
LONGPORT_MIN_ORDER_AMOUNT=100  # 最小下单金额（美元）

# 交易设置
LONGPORT_AUTO_TRADE=false  # 是否启用自动交易（true=自动下单，false=仅监控）
LONGPORT_DRY_RUN=true  # 是否启用模拟模式（true=不实际下单，仅打印日志）
"""


def create_env_template():
    """创建 .env.example 模板文件"""
    env_example_path = ".env.example"
    if not os.path.exists(env_example_path):
        with open(env_example_path, "w", encoding="utf-8") as f:
            f.write(ENV_TEMPLATE)
        print(f"已创建配置模板: {env_example_path}")
        print("请复制为 .env 并填写你的凭据")