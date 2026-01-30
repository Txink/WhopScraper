"""
长桥 OpenAPI 配置加载器
支持模拟账户和真实账户的自动切换
"""
import os
from typing import Optional
from longport.openapi import Config
from dotenv import load_dotenv
import logging

logger = logging.getLogger(__name__)

# 加载环境变量
load_dotenv()


class LongPortConfigLoader:
    """长桥配置加载器"""
    
    PAPER_MODE = "paper"  # 模拟账户
    REAL_MODE = "real"    # 真实账户
    
    def __init__(self, mode: Optional[str] = None):
        """
        初始化配置加载器
        
        Args:
            mode: 账户模式 'paper' 或 'real'，如果不指定则从环境变量读取
        """
        self.mode = mode or os.getenv("LONGPORT_MODE", self.PAPER_MODE)
        self._validate_mode()
        self._config = None
    
    def _validate_mode(self):
        """验证账户模式"""
        if self.mode not in [self.PAPER_MODE, self.REAL_MODE]:
            raise ValueError(
                f"Invalid LONGPORT_MODE: {self.mode}. "
                f"Must be '{self.PAPER_MODE}' or '{self.REAL_MODE}'"
            )
    
    def get_config(self) -> Config:
        """
        获取长桥配置对象
        
        Returns:
            Config: 长桥 SDK 配置对象
        """
        if self._config is not None:
            return self._config
        
        if self.mode == self.PAPER_MODE:
            logger.info("🧪 使用模拟账户 (Paper Trading)")
            self._config = self._load_paper_config()
        else:
            logger.warning("💰 使用真实账户 (Real Trading) - 请谨慎操作！")
            self._config = self._load_real_config()
        
        # 设置区域
        region = os.getenv("LONGPORT_REGION", "cn")
        logger.info(f"API 接入点: {region}")
        
        return self._config
    
    def _load_paper_config(self) -> Config:
        """加载模拟账户配置"""
        app_key = os.getenv("LONGPORT_PAPER_APP_KEY")
        app_secret = os.getenv("LONGPORT_PAPER_APP_SECRET")
        access_token = os.getenv("LONGPORT_PAPER_ACCESS_TOKEN")
        
        if not all([app_key, app_secret, access_token]):
            raise ValueError(
                "模拟账户凭证不完整！请在 .env 文件中配置：\n"
                "  - LONGPORT_PAPER_APP_KEY\n"
                "  - LONGPORT_PAPER_APP_SECRET\n"
                "  - LONGPORT_PAPER_ACCESS_TOKEN"
            )
        
        return Config(
            app_key=app_key,
            app_secret=app_secret,
            access_token=access_token
        )
    
    def _load_real_config(self) -> Config:
        """加载真实账户配置"""
        app_key = os.getenv("LONGPORT_REAL_APP_KEY")
        app_secret = os.getenv("LONGPORT_REAL_APP_SECRET")
        access_token = os.getenv("LONGPORT_REAL_ACCESS_TOKEN")
        
        if not all([app_key, app_secret, access_token]):
            raise ValueError(
                "真实账户凭证不完整！请在 .env 文件中配置：\n"
                "  - LONGPORT_REAL_APP_KEY\n"
                "  - LONGPORT_REAL_APP_SECRET\n"
                "  - LONGPORT_REAL_ACCESS_TOKEN"
            )
        
        # 安全检查：防止误操作
        auto_trade = os.getenv("LONGPORT_AUTO_TRADE", "false").lower() == "true"
        dry_run = os.getenv("LONGPORT_DRY_RUN", "true").lower() == "true"
        
        if not auto_trade:
            logger.warning("⚠️  LONGPORT_AUTO_TRADE=false，将不会自动下单")
        
        if dry_run:
            logger.warning("⚠️  LONGPORT_DRY_RUN=true，模拟模式已启用，不会真实下单")
        
        return Config(
            app_key=app_key,
            app_secret=app_secret,
            access_token=access_token
        )
    
    def is_paper_mode(self) -> bool:
        """是否为模拟账户模式"""
        return self.mode == self.PAPER_MODE
    
    def is_real_mode(self) -> bool:
        """是否为真实账户模式"""
        return self.mode == self.REAL_MODE
    
    def is_auto_trade_enabled(self) -> bool:
        """是否启用自动交易"""
        return os.getenv("LONGPORT_AUTO_TRADE", "false").lower() == "true"
    
    def is_dry_run(self) -> bool:
        """是否为模拟运行模式（不实际下单）"""
        return os.getenv("LONGPORT_DRY_RUN", "true").lower() == "true"
    
    def get_risk_config(self) -> dict:
        """获取风险控制配置"""
        return {
            "max_position_ratio": float(os.getenv("LONGPORT_MAX_POSITION_RATIO", "0.20")),
            "max_daily_loss": float(os.getenv("LONGPORT_MAX_DAILY_LOSS", "0.05")),
            "min_order_amount": float(os.getenv("LONGPORT_MIN_ORDER_AMOUNT", "100"))
        }
    
    def print_config_summary(self):
        """打印配置摘要"""
        print("\n" + "=" * 60)
        print("长桥 OpenAPI 配置摘要")
        print("=" * 60)
        print(f"账户模式:     {'🧪 模拟账户' if self.is_paper_mode() else '💰 真实账户'}")
        print(f"自动交易:     {'✅ 已启用' if self.is_auto_trade_enabled() else '❌ 未启用'}")
        print(f"模拟运行:     {'✅ 已启用 (不实际下单)' if self.is_dry_run() else '❌ 未启用'}")
        print(f"API 区域:     {os.getenv('LONGPORT_REGION', 'cn')}")
        
        risk_config = self.get_risk_config()
        print(f"\n风险控制:")
        print(f"  单仓位上限:   {risk_config['max_position_ratio']*100:.1f}%")
        print(f"  单日止损:     {risk_config['max_daily_loss']*100:.1f}%")
        print(f"  最小下单额:   ${risk_config['min_order_amount']:.0f}")
        print("=" * 60 + "\n")


def load_longport_config(mode: Optional[str] = None) -> Config:
    """
    快捷函数：加载长桥配置
    
    Args:
        mode: 账户模式 'paper' 或 'real'
    
    Returns:
        Config: 长桥 SDK 配置对象
    
    Example:
        >>> config = load_longport_config()  # 从环境变量读取模式
        >>> config = load_longport_config("paper")  # 强制使用模拟账户
    """
    loader = LongPortConfigLoader(mode)
    loader.print_config_summary()
    return loader.get_config()


if __name__ == "__main__":
    # 测试配置加载
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    try:
        # 测试加载配置
        config = load_longport_config()
        print("✅ 配置加载成功！")
        
        # 测试连接
        from longport.openapi import TradeContext
        ctx = TradeContext(config)
        balance = ctx.account_balance()
        
        print("\n账户信息:")
        for b in balance:
            print(f"  币种: {b.currency}, 总资金: {b.total_cash:,.2f}")
        
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        sys.exit(1)
