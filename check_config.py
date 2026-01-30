#!/usr/bin/env python3
"""
配置检查工具
快速验证 .env 配置是否正确
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()


def print_header(title):
    """打印标题"""
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def check_file_exists():
    """检查配置文件是否存在"""
    print_header("📁 配置文件检查")
    
    env_file = Path(".env")
    env_example = Path(".env.example")
    
    issues = []
    
    if env_file.exists():
        print("✅ .env 文件存在")
    else:
        print("❌ .env 文件不存在")
        print("   请运行: cp .env.example .env")
        issues.append(".env 文件")
    
    if env_example.exists():
        print("✅ .env.example 文件存在")
    else:
        print("⚠️  .env.example 文件不存在")
        issues.append(".env.example 文件")
    
    return len(issues) == 0, issues


def check_whop_config():
    """检查 Whop 配置"""
    print_header("📧 Whop 平台配置")
    
    email = os.getenv("WHOP_EMAIL")
    password = os.getenv("WHOP_PASSWORD")
    
    issues = []
    
    if email and email != "your_email@example.com":
        print(f"✅ WHOP_EMAIL: {email}")
    else:
        print(f"❌ WHOP_EMAIL: 未配置或使用默认值")
        issues.append("WHOP_EMAIL")
    
    if password and password != "your_password":
        print(f"✅ WHOP_PASSWORD: ***（已设置）")
    else:
        print(f"❌ WHOP_PASSWORD: 未配置或使用默认值")
        issues.append("WHOP_PASSWORD")
    
    target_url = os.getenv("TARGET_URL")
    if target_url:
        print(f"✅ TARGET_URL: {target_url}")
    else:
        print(f"ℹ️  TARGET_URL: 使用默认值")
    
    login_url = os.getenv("LOGIN_URL")
    if login_url:
        print(f"✅ LOGIN_URL: {login_url}")
    else:
        print(f"ℹ️  LOGIN_URL: 使用默认值")
    
    return len(issues) == 0, issues


def check_longport_config():
    """检查长桥配置"""
    print_header("💰 长桥证券配置")
    
    mode = os.getenv("LONGPORT_MODE", "paper")
    print(f"📌 账户模式: {mode}")
    
    issues = []
    
    if mode == "paper":
        # 检查模拟账户配置
        paper_configs = {
            "LONGPORT_PAPER_APP_KEY": os.getenv("LONGPORT_PAPER_APP_KEY"),
            "LONGPORT_PAPER_APP_SECRET": os.getenv("LONGPORT_PAPER_APP_SECRET"),
            "LONGPORT_PAPER_ACCESS_TOKEN": os.getenv("LONGPORT_PAPER_ACCESS_TOKEN"),
        }
        
        for key, value in paper_configs.items():
            if value and not value.startswith("your_"):
                print(f"✅ {key}: ***（已设置）")
            else:
                print(f"❌ {key}: 未配置或使用默认值")
                issues.append(key)
    
    elif mode == "real":
        # 检查真实账户配置
        real_configs = {
            "LONGPORT_REAL_APP_KEY": os.getenv("LONGPORT_REAL_APP_KEY"),
            "LONGPORT_REAL_APP_SECRET": os.getenv("LONGPORT_REAL_APP_SECRET"),
            "LONGPORT_REAL_ACCESS_TOKEN": os.getenv("LONGPORT_REAL_ACCESS_TOKEN"),
        }
        
        for key, value in real_configs.items():
            if value and not value.startswith("your_"):
                print(f"✅ {key}: ***（已设置）")
            else:
                print(f"❌ {key}: 未配置或使用默认值")
                issues.append(key)
        
        print("\n⚠️  警告: 使用真实账户模式！")
    
    # 通用配置
    print(f"\n通用配置:")
    print(f"  LONGPORT_REGION: {os.getenv('LONGPORT_REGION', 'cn')}")
    print(f"  LONGPORT_AUTO_TRADE: {os.getenv('LONGPORT_AUTO_TRADE', 'false')}")
    print(f"  LONGPORT_DRY_RUN: {os.getenv('LONGPORT_DRY_RUN', 'true')}")
    
    return len(issues) == 0, issues


def check_risk_config():
    """检查风险控制配置"""
    print_header("🛡️ 风险控制配置")
    
    max_position = float(os.getenv("LONGPORT_MAX_POSITION_RATIO", "0.20"))
    max_loss = float(os.getenv("LONGPORT_MAX_DAILY_LOSS", "0.05"))
    min_amount = int(os.getenv("LONGPORT_MIN_ORDER_AMOUNT", "100"))
    
    print(f"✅ 单仓位上限: {max_position*100:.1f}%")
    print(f"✅ 单日止损: {max_loss*100:.1f}%")
    print(f"✅ 最小下单额: ${min_amount}")
    
    # 合理性检查
    warnings = []
    
    if max_position > 0.5:
        warnings.append("⚠️  单仓位上限过高（>50%），建议设置在 10%-30% 之间")
    
    if max_loss > 0.2:
        warnings.append("⚠️  单日止损过高（>20%），建议设置在 3%-10% 之间")
    
    if min_amount < 50:
        warnings.append("⚠️  最小下单额过低（<$50），可能产生过多小额交易")
    
    if warnings:
        print("\n风险提示:")
        for warning in warnings:
            print(f"  {warning}")
    
    return True, []


def check_trading_mode():
    """检查交易模式配置"""
    print_header("⚙️ 交易模式")
    
    auto_trade = os.getenv("LONGPORT_AUTO_TRADE", "false").lower() == "true"
    dry_run = os.getenv("LONGPORT_DRY_RUN", "true").lower() == "true"
    mode = os.getenv("LONGPORT_MODE", "paper")
    
    print(f"账户模式: {'🧪 模拟账户' if mode == 'paper' else '💰 真实账户'}")
    print(f"自动交易: {'✅ 启用' if auto_trade else '❌ 禁用'}")
    print(f"Dry Run: {'✅ 启用（不实际下单）' if dry_run else '❌ 禁用（会实际下单）'}")
    
    # 模式组合建议
    print("\n当前模式组合:")
    if mode == "paper" and auto_trade and dry_run:
        print("  🧪 测试模式 - 完全安全（推荐新手）")
    elif mode == "paper" and auto_trade and not dry_run:
        print("  🎯 模拟交易模式 - 在模拟账户测试")
    elif mode == "real" and auto_trade and not dry_run:
        print("  💸 生产模式 - 真实账户真实交易")
        print("  ⚠️  警告: 会产生真实交易！")
    else:
        print("  📊 监控模式 - 仅监控不交易")
    
    return True, []


def main():
    """主函数"""
    print("\n" + "="*60)
    print("🔍 配置检查工具")
    print("="*60)
    print("验证 .env 配置是否正确...")
    
    all_passed = True
    all_issues = []
    
    # 运行所有检查
    checks = [
        check_file_exists,
        check_whop_config,
        check_longport_config,
        check_risk_config,
        check_trading_mode,
    ]
    
    for check in checks:
        try:
            passed, issues = check()
            if not passed:
                all_passed = False
                all_issues.extend(issues)
        except Exception as e:
            print(f"❌ 检查失败: {e}")
            all_passed = False
    
    # 输出总结
    print_header("📊 检查总结")
    
    if all_passed:
        print("✅ 所有配置检查通过！")
        print("\n下一步:")
        print("  1. 运行测试: ./run_all_tests.sh")
        print("  2. 启动系统: python3 main.py")
    else:
        print("❌ 配置存在问题，请修复以下项目:")
        for issue in all_issues:
            print(f"  - {issue}")
        print("\n修复方法:")
        print("  1. 编辑 .env 文件")
        print("  2. 参考文档: doc/CONFIGURATION.md")
        print("  3. 重新运行此检查: python3 check_config.py")
    
    print("\n" + "="*60)
    print("📖 详细配置说明: doc/CONFIGURATION.md")
    print("="*60 + "\n")
    
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
