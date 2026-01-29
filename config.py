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
    LOGIN_URL: str = "https://whop.com/login/"
    
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
ENV_TEMPLATE = """# Whop 登录凭据
WHOP_EMAIL=your_email@example.com
WHOP_PASSWORD=your_password

# 目标页面 URL（可选，有默认值）
# TARGET_URL=https://whop.com/joined/stock-and-option/-9vfxZgBNgXykNt/app/

# 浏览器设置
HEADLESS=false
SLOW_MO=0

# 监控设置
POLL_INTERVAL=2.0

# Cookie 持久化路径
# STORAGE_STATE_PATH=storage_state.json

# 输出设置
# OUTPUT_FILE=output/signals.json
"""


def create_env_template():
    """创建 .env.example 模板文件"""
    env_example_path = ".env.example"
    if not os.path.exists(env_example_path):
        with open(env_example_path, "w", encoding="utf-8") as f:
            f.write(ENV_TEMPLATE)
        print(f"已创建配置模板: {env_example_path}")
        print("请复制为 .env 并填写你的凭据")
