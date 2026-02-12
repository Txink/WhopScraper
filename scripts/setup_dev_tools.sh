#!/bin/bash
#
# 开发工具安装脚本
# 功能：安装 Xcode CLT、Git、Homebrew（阿里源）、lazygit
#

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# ============================================================
# 0. 安装 Xcode Command Line Tools（macOS 前置依赖）
# ============================================================
install_xcode_cli() {
    if [[ "$(uname)" != "Darwin" ]]; then
        return 0
    fi

    info "检查 Xcode Command Line Tools 安装状态..."
    if xcode-select -p &>/dev/null; then
        info "Xcode Command Line Tools 已安装: $(xcode-select -p)"
    else
        info "正在安装 Xcode Command Line Tools..."
        info "这是 macOS 上 Git、Homebrew 等工具的前置依赖"
        xcode-select --install

        # 等待用户完成安装
        info "请在弹出的窗口中点击「安装」，安装完成后按回车继续..."
        read -r -p "按回车继续 >"

        # 验证安装结果
        if xcode-select -p &>/dev/null; then
            info "Xcode Command Line Tools 安装成功!"
        else
            error "Xcode Command Line Tools 安装失败，请手动执行: xcode-select --install"
            exit 1
        fi
    fi
}

# ============================================================
# 1. 安装 Git
# ============================================================
install_git() {
    info "检查 Git 安装状态..."
    if command -v git &>/dev/null; then
        local git_version
        git_version=$(git --version)
        info "Git 已安装: ${git_version}"
    else
        info "正在安装 Git..."
        if [[ "$(uname)" == "Darwin" ]]; then
            # macOS: Xcode CLT 已在前面安装，此处重新检查
            if xcode-select -p &>/dev/null; then
                info "Xcode Command Line Tools 已安装，Git 应已可用"
            else
                error "请先安装 Xcode Command Line Tools"
                return 1
            fi
        elif [[ -f /etc/debian_version ]]; then
            sudo apt-get update && sudo apt-get install -y git
        elif [[ -f /etc/redhat-release ]]; then
            sudo yum install -y git
        else
            error "无法识别的操作系统，请手动安装 Git"
            return 1
        fi
    fi
}

# ============================================================
# 2. 安装 Homebrew（使用阿里云镜像源）
# ============================================================
install_brew() {
    info "检查 Homebrew 安装状态..."
    if command -v brew &>/dev/null; then
        info "Homebrew 已安装: $(brew --version | head -1)"
        info "正在配置阿里云镜像源..."
        set_brew_alibaba_mirror
    else
        info "正在使用阿里云镜像安装 Homebrew..."

        # 设置阿里云镜像环境变量，加速安装
        export HOMEBREW_API_DOMAIN="https://mirrors.aliyun.com/homebrew/homebrew-bottles/api"
        export HOMEBREW_BREW_GIT_REMOTE="https://mirrors.aliyun.com/homebrew/brew.git"
        export HOMEBREW_CORE_GIT_REMOTE="https://mirrors.aliyun.com/homebrew/homebrew-core.git"
        export HOMEBREW_BOTTLE_DOMAIN="https://mirrors.aliyun.com/homebrew/homebrew-bottles"

        # 使用官方安装脚本（会自动使用上面设置的环境变量）
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

        # 安装后配置 PATH
        if [[ "$(uname -m)" == "arm64" ]]; then
            BREW_PREFIX="/opt/homebrew"
        else
            BREW_PREFIX="/usr/local"
        fi

        if [[ -x "${BREW_PREFIX}/bin/brew" ]]; then
            eval "$(${BREW_PREFIX}/bin/brew shellenv)"
        fi

        info "Homebrew 安装完成，正在配置阿里云镜像源..."
        set_brew_alibaba_mirror
    fi
}

set_brew_alibaba_mirror() {
    # 检测当前使用的 shell 配置文件
    local shell_profile
    if [[ -n "$ZSH_VERSION" ]] || [[ "$SHELL" == */zsh ]]; then
        shell_profile="$HOME/.zshrc"
    elif [[ -n "$BASH_VERSION" ]] || [[ "$SHELL" == */bash ]]; then
        shell_profile="$HOME/.bash_profile"
    else
        shell_profile="$HOME/.profile"
    fi

    info "Shell 配置文件: ${shell_profile}"

    # 定义需要写入的环境变量
    local mirror_vars=(
        'export HOMEBREW_API_DOMAIN="https://mirrors.aliyun.com/homebrew/homebrew-bottles/api"'
        'export HOMEBREW_BREW_GIT_REMOTE="https://mirrors.aliyun.com/homebrew/brew.git"'
        'export HOMEBREW_CORE_GIT_REMOTE="https://mirrors.aliyun.com/homebrew/homebrew-core.git"'
        'export HOMEBREW_BOTTLE_DOMAIN="https://mirrors.aliyun.com/homebrew/homebrew-bottles"'
    )

    # 写入配置文件（避免重复添加）
    for var in "${mirror_vars[@]}"; do
        if ! grep -qF "$var" "$shell_profile" 2>/dev/null; then
            echo "$var" >> "$shell_profile"
        fi
    done

    # 使当前 shell 生效
    export HOMEBREW_API_DOMAIN="https://mirrors.aliyun.com/homebrew/homebrew-bottles/api"
    export HOMEBREW_BREW_GIT_REMOTE="https://mirrors.aliyun.com/homebrew/brew.git"
    export HOMEBREW_CORE_GIT_REMOTE="https://mirrors.aliyun.com/homebrew/homebrew-core.git"
    export HOMEBREW_BOTTLE_DOMAIN="https://mirrors.aliyun.com/homebrew/homebrew-bottles"

    info "阿里云镜像源已配置到 ${shell_profile}"
    info "当前 session 已生效，新终端打开后也会自动使用阿里云镜像"
}

# ============================================================
# 3. 使用 Homebrew 安装 lazygit
# ============================================================
install_lazygit() {
    info "检查 lazygit 安装状态..."
    if command -v lazygit &>/dev/null; then
        local lg_version
        lg_version=$(lazygit --version | head -1)
        info "lazygit 已安装: ${lg_version}"
    else
        if ! command -v brew &>/dev/null; then
            error "Homebrew 未安装，无法安装 lazygit"
            return 1
        fi
        info "正在通过 Homebrew 安装 lazygit..."
        brew install lazygit
        info "lazygit 安装完成!"
    fi
}

# ============================================================
# 主流程
# ============================================================
main() {
    echo "========================================"
    echo "  开发工具安装脚本"
    echo "  安装内容: Xcode CLT / Git / Homebrew / lazygit"
    echo "========================================"
    echo ""

    install_xcode_cli
    echo ""

    install_git
    echo ""

    install_brew
    echo ""

    install_lazygit
    echo ""

    echo "========================================"
    info "所有工具安装完成！"
    echo "========================================"

    # 显示安装结果
    echo ""
    info "安装结果:"
    echo "  Git:     $(command -v git &>/dev/null && git --version || echo '未安装')"
    echo "  Brew:    $(command -v brew &>/dev/null && brew --version | head -1 || echo '未安装')"
    echo "  lazygit: $(command -v lazygit &>/dev/null && echo '已安装' || echo '未安装')"
    echo ""
    warn "如果是首次安装 Homebrew，请执行以下命令使配置生效："
    echo "  source ~/.zshrc"
}

main "$@"
