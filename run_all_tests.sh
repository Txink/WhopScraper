#!/bin/bash
# 运行所有测试脚本

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 切换到项目根目录
cd "$(dirname "$0")"

echo -e "${BLUE}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║           运行所有测试 - All Tests Runner               ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# 测试计数器
TOTAL_TESTS=6
PASSED_TESTS=0
FAILED_TESTS=0

# 运行单个测试
run_test() {
    local test_name=$1
    local test_file=$2
    
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}📝 测试: ${test_name}${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    
    PYTHONPATH=. python3 "$test_file"
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✅ ${test_name} - 通过${NC}"
        ((PASSED_TESTS++))
    else
        echo -e "${RED}❌ ${test_name} - 失败${NC}"
        ((FAILED_TESTS++))
    fi
    echo ""
}

# 运行各项测试
run_test "配置加载测试" "test/test_config.py"
run_test "长桥 API 集成测试" "test/test_longport_integration.py"
run_test "期权过期校验测试" "test/test_option_expiry.py"
run_test "期权过期集成测试" "test/test_expiry_integration.py"
run_test "持仓管理测试" "test/test_position_management.py"
run_test "样本管理测试" "test/test_samples.py"

# 输出总结
echo -e "${BLUE}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║                     测试总结                             ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "总测试数: ${TOTAL_TESTS}"
echo -e "${GREEN}通过: ${PASSED_TESTS}${NC}"
echo -e "${RED}失败: ${FAILED_TESTS}${NC}"
echo ""

if [ $FAILED_TESTS -eq 0 ]; then
    echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║              🎉 所有测试通过！All Tests Passed!          ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
    exit 0
else
    echo -e "${RED}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${RED}║          ⚠️  部分测试失败 - Some Tests Failed           ║${NC}"
    echo -e "${RED}╚══════════════════════════════════════════════════════════╝${NC}"
    exit 1
fi
