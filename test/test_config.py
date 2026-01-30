"""
测试配置加载功能
验证所有配置项都能从 .env 文件正确加载
"""
import os
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import Config


def test_whop_config():
    """测试 Whop 配置"""
    print("\n" + "="*60)
    print("测试 1: Whop 平台配置")
    print("="*60)
    
    configs = {
        "WHOP_EMAIL": Config.WHOP_EMAIL,
        "WHOP_PASSWORD": Config.WHOP_PASSWORD,
        "TARGET_URL": Config.TARGET_URL,
        "LOGIN_URL": Config.LOGIN_URL,
    }
    
    for key, value in configs.items():
        status = "✅" if value else "⚠️"
        print(f"{status} {key}: {value if not 'PASSWORD' in key else '***'}")
    
    return all(configs.values())


def test_browser_config():
    """测试浏览器配置"""
    print("\n" + "="*60)
    print("测试 2: 浏览器配置")
    print("="*60)
    
    configs = {
        "HEADLESS": Config.HEADLESS,
        "SLOW_MO": Config.SLOW_MO,
    }
    
    for key, value in configs.items():
        print(f"✅ {key}: {value} (类型: {type(value).__name__})")
    
    # 验证类型
    assert isinstance(Config.HEADLESS, bool), "HEADLESS 应该是布尔值"
    assert isinstance(Config.SLOW_MO, int), "SLOW_MO 应该是整数"
    
    print("✅ 类型验证通过")
    return True


def test_monitor_config():
    """测试监控配置"""
    print("\n" + "="*60)
    print("测试 3: 监控配置")
    print("="*60)
    
    configs = {
        "POLL_INTERVAL": Config.POLL_INTERVAL,
        "STORAGE_STATE_PATH": Config.STORAGE_STATE_PATH,
        "OUTPUT_FILE": Config.OUTPUT_FILE,
    }
    
    for key, value in configs.items():
        print(f"✅ {key}: {value} (类型: {type(value).__name__})")
    
    # 验证类型
    assert isinstance(Config.POLL_INTERVAL, float), "POLL_INTERVAL 应该是浮点数"
    assert isinstance(Config.STORAGE_STATE_PATH, str), "STORAGE_STATE_PATH 应该是字符串"
    assert isinstance(Config.OUTPUT_FILE, str), "OUTPUT_FILE 应该是字符串"
    
    print("✅ 类型验证通过")
    return True


def test_default_values():
    """测试默认值"""
    print("\n" + "="*60)
    print("测试 4: 默认值测试")
    print("="*60)
    
    # 测试有默认值的配置项
    defaults = {
        "TARGET_URL": "https://whop.com/joined/stock-and-option/-9vfxZgBNgXykNt/app/",
        "LOGIN_URL": "https://whop.com/login/",
        "HEADLESS": False,
        "SLOW_MO": 0,
        "POLL_INTERVAL": 2.0,
        "STORAGE_STATE_PATH": "storage_state.json",
        "OUTPUT_FILE": "output/signals.json",
    }
    
    for key, expected_default in defaults.items():
        actual = getattr(Config, key)
        # 如果环境变量未设置，应该使用默认值
        if os.getenv(key) is None:
            if actual == expected_default:
                print(f"✅ {key}: 使用默认值 {actual}")
            else:
                print(f"⚠️  {key}: 期望 {expected_default}, 实际 {actual}")
        else:
            print(f"✅ {key}: 从环境变量加载 {actual}")
    
    return True


def test_env_file_exists():
    """测试 .env 文件是否存在"""
    print("\n" + "="*60)
    print("测试 5: 环境文件检查")
    print("="*60)
    
    env_path = Path(".env")
    env_example_path = Path(".env.example")
    
    if env_path.exists():
        print(f"✅ .env 文件存在")
    else:
        print(f"⚠️  .env 文件不存在（请从 .env.example 复制）")
    
    if env_example_path.exists():
        print(f"✅ .env.example 文件存在")
    else:
        print(f"❌ .env.example 文件不存在")
    
    return env_example_path.exists()


def test_validation():
    """测试配置验证"""
    print("\n" + "="*60)
    print("测试 6: 配置验证")
    print("="*60)
    
    is_valid = Config.validate()
    
    if is_valid:
        print("✅ 配置验证通过 - 所有必需配置项已设置")
    else:
        print("⚠️  配置验证失败 - 请检查 WHOP_EMAIL 和 WHOP_PASSWORD")
    
    return is_valid


def test_all_env_vars():
    """测试所有环境变量"""
    print("\n" + "="*60)
    print("测试 7: 所有环境变量")
    print("="*60)
    
    env_vars = [
        # Whop 配置
        "WHOP_EMAIL",
        "WHOP_PASSWORD",
        "TARGET_URL",
        "LOGIN_URL",
        "HEADLESS",
        "SLOW_MO",
        "POLL_INTERVAL",
        "STORAGE_STATE_PATH",
        "OUTPUT_FILE",
        
        # 长桥配置
        "LONGPORT_MODE",
        "LONGPORT_PAPER_APP_KEY",
        "LONGPORT_PAPER_APP_SECRET",
        "LONGPORT_PAPER_ACCESS_TOKEN",
        "LONGPORT_REAL_APP_KEY",
        "LONGPORT_REAL_APP_SECRET",
        "LONGPORT_REAL_ACCESS_TOKEN",
        "LONGPORT_REGION",
        "LONGPORT_ENABLE_OVERNIGHT",
        "LONGPORT_MAX_POSITION_RATIO",
        "LONGPORT_MAX_DAILY_LOSS",
        "LONGPORT_MIN_ORDER_AMOUNT",
        "LONGPORT_AUTO_TRADE",
        "LONGPORT_DRY_RUN",
    ]
    
    print(f"检查 {len(env_vars)} 个环境变量...")
    
    set_count = 0
    unset_count = 0
    
    for var in env_vars:
        value = os.getenv(var)
        if value:
            set_count += 1
            # 敏感信息不显示
            if any(keyword in var for keyword in ['PASSWORD', 'SECRET', 'TOKEN', 'KEY']):
                print(f"  ✅ {var}: ***")
            else:
                print(f"  ✅ {var}: {value}")
        else:
            unset_count += 1
            print(f"  ⚪ {var}: (未设置)")
    
    print(f"\n统计: {set_count} 个已设置, {unset_count} 个未设置")
    return True


if __name__ == "__main__":
    print("\n" + "="*60)
    print("🚀 配置加载测试")
    print("="*60)
    print("\n💡 本测试验证所有配置项都能从 .env 文件正确加载")
    
    tests = [
        test_env_file_exists,
        test_whop_config,
        test_browser_config,
        test_monitor_config,
        test_default_values,
        test_validation,
        test_all_env_vars,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"❌ 测试异常: {e}")
            failed += 1
    
    print("\n" + "="*60)
    print(f"测试总结: {passed} 通过, {failed} 失败")
    print("="*60)
    
    if failed == 0:
        print("✅ 所有配置测试通过！")
        print("\n💡 提示:")
        print("  - 所有配置都从 .env 文件加载")
        print("  - 详细配置说明请查看: doc/CONFIGURATION.md")
    else:
        print("⚠️  部分测试失败，请检查配置")
    
    sys.exit(0 if failed == 0 else 1)
