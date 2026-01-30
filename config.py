"""
配置模块 - 管理凭据和应用设置
"""
import os
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()


class Config:
    """应用配置"""
    
    # Whop 登录凭据
    WHOP_EMAIL: str = os.getenv("WHOP_EMAIL", "")
    WHOP_PASSWORD: str = os.getenv("WHOP_PASSWORD", "")
    
    # 目标页面 URL
    TARGET_URL: str = os.getenv(
        "TARGET_URL",
        "https://whop.com/joined/stock-and-option/-9vfxZgBNgXykNt/app/"
    )
    
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
    
    @classmethod
    def validate(cls) -> bool:
        """验证必需的配置项"""
        if not cls.WHOP_EMAIL or not cls.WHOP_PASSWORD:
            print("错误: 请设置 WHOP_EMAIL 和 WHOP_PASSWORD 环境变量")
            print("可以在 .env 文件中设置，或直接设置环境变量")
            return False
        return True


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