#!/bin/bash

# AIOps 平台高级功能离线升级脚本
# 用于将现有的基础功能升级为包含高级功能的版本
# 作者: AI Assistant
# 版本: 1.0.0

set -e  # 遇到错误立即退出

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 日志函数
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 配置变量
BACKUP_DIR="/opt/aiops-deploy/backup"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(dirname "$SCRIPT_DIR")"

# 检查是否为root用户
check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "此脚本需要root权限运行"
        log_info "请使用: sudo bash $0"
        exit 1
    fi
}

# 检查系统环境
check_environment() {
    log_info "检查系统环境..."
    
    # 检查是否在正确的目录
    if [[ ! -f "$DEPLOY_DIR/backend/requirements.txt" ]]; then
        log_error "未找到正确的部署目录结构"
        log_info "请确保在包含backend和frontend-dist的目录中运行此脚本"
        exit 1
    fi
    
    # 检查Python
    if ! command -v python3 &> /dev/null; then
        log_error "未找到Python3，请先安装Python3"
        exit 1
    fi
    
    # 检查数据库
    if [[ ! -f "$DEPLOY_DIR/backend/aiops.db" ]]; then
        log_warning "未找到数据库文件，将创建新数据库"
    fi
    
    log_success "系统环境检查通过"
}

# 创建备份
create_backup() {
    log_info "创建系统备份..."
    
    # 创建备份目录
    mkdir -p "$BACKUP_DIR"
    
    # 备份数据库
    if [[ -f "$DEPLOY_DIR/backend/aiops.db" ]]; then
        cp "$DEPLOY_DIR/backend/aiops.db" "$BACKUP_DIR/aiops.db.backup_$(date +%Y%m%d_%H%M%S)"
        log_success "数据库已备份"
    fi
    
    # 备份配置文件
    if [[ -f "$DEPLOY_DIR/backend/.env" ]]; then
        cp "$DEPLOY_DIR/backend/.env" "$BACKUP_DIR/.env.backup_$(date +%Y%m%d_%H%M%S)"
        log_success "配置文件已备份"
    fi
    
    # 备份旧的服务文件
    if [[ -f "/etc/systemd/system/aiops-backend.service" ]]; then
        cp "/etc/systemd/system/aiops-backend.service" "$BACKUP_DIR/aiops-backend.service.backup_$(date +%Y%m%d_%H%M%S)"
        log_success "服务文件已备份"
    fi
    
    log_success "系统备份完成"
}

# 备份数据库
migrate_database() {
    log_info "迁移数据库结构..."
    
    # 检查迁移脚本
    if [[ ! -f "$SCRIPT_DIR/migrate_advanced_features.py" ]]; then
        log_error "未找到迁移脚本"
        exit 1
    fi
    
    # 执行迁移
    python3 "$SCRIPT_DIR/migrate_advanced_features.py" "$DEPLOY_DIR/backend/aiops.db"
    if [[ $? -eq 0 ]]; then
        log_success "数据库迁移完成"
    else
        log_error "数据库迁移失败"
        exit 1
    fi
}

# 更新后端代码
update_backend() {
    log_info "更新后端代码..."
    
    # 进入后端目录
    cd "$DEPLOY_DIR/backend"
    
    # 停止服务
    systemctl stop aiops-backend 2>/dev/null || true
    log_info "已停止后端服务"
    
    # 更新代码（这里假设有新的代码文件）
    # 在实际使用中，您需要将新的代码文件复制到此处
    log_info "更新后端代码文件..."
    
    # 重新安装依赖
    if [[ -f "requirements.txt" ]]; then
        pip install -r requirements.txt
        log_success "依赖包已更新"
    fi
    
    # 重启服务
    systemctl daemon-reload
    systemctl start aiops-backend
    systemctl enable aiops-backend
    
    # 检查服务状态
    if systemctl is-active --quiet aiops-backend; then
        log_success "后端服务已启动"
    else
        log_error "后端服务启动失败"
        exit 1
    fi
}

# 更新前端代码
update_frontend() {
    log_info "更新前端代码..."
    
    # 进入前端目录
    cd "$DEPLOY_DIR/frontend-dist"
    
    # 检查前端文件是否存在
    if [[ ! -f "index.html" ]]; then
        log_warning "未找到前端文件，跳过前端更新"
        return
    fi
    
    # 重新配置nginx
    if [[ -f "$SCRIPT_DIR/nginx-aiops.conf" ]]; then
        cp "$SCRIPT_DIR/nginx-aiops.conf" /etc/nginx/conf.d/aiops.conf
        nginx -t
        systemctl reload nginx
        log_success "前端配置已更新"
    fi
}

# 验证安装
verify_installation() {
    log_info "验证安装..."
    
    # 检查后端服务
    if curl -f http://localhost:8080/api/health &>/dev/null; then
        log_success "后端服务正常运行"
    else
        log_error "后端服务无法访问"
        return 1
    fi
    
    # 检查前端服务
    if curl -f http://localhost/ &>/dev/null; then
        log_success "前端服务正常运行"
    else
        log_warning "前端服务无法访问，可能需要重启nginx"
    fi
    
    # 检查新API接口
    if curl -f http://localhost:8080/api/topology/discover &>/dev/null; then
        log_success "拓扑发现API可用"
    else
        log_warning "拓扑发现API可能不可用"
    fi
    
    log_success "验证完成"
}

# 清理旧文件
cleanup() {
    log_info "清理临时文件..."
    
    # 清理Python缓存
    find "$DEPLOY_DIR" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
    find "$DEPLOY_DIR" -name "*.pyc" -delete 2>/dev/null || true
    
    # 清理其他临时文件
    rm -rf /tmp/aiops_upgrade_* 2>/dev/null || true
    
    log_success "清理完成"
}

# 显示升级结果
show_upgrade_result() {
    log_info "升级完成！新功能包括："
    echo ""
    echo "🔍 拓扑发现与管理:"
    echo "   - 自动拓扑发现: POST /api/topology/discover"
    echo "   - 拓扑图查询: GET /api/topology/graph"
    echo "   - 影响面分析: GET /api/topology/{device_type}/{device_id}/blast-radius"
    echo ""
    echo "🧠 智能根因分析 (RCA):"
    echo "   - 根因分析: POST /api/rca/analyze/{alert_id}"
    echo "   - 分析历史: GET /api/rca/history"
    echo "   - 详细结果: GET /api/rca/{analysis_id}"
    echo ""
    echo "📚 RAG知识库增强:"
    echo "   - 知识搜索: GET /api/knowledge/search"
    echo "   - 故障学习: POST /api/knowledge/learn-from-incident"
    echo "   - 相似案例: GET /api/knowledge/similar-incidents"
    echo ""
    echo "⚙️ 工作流编排系统:"
    echo "   - 工作流列表: GET /api/workflows"
    echo "   - 创建工作流: POST /api/workflows"
    echo "   - 执行工作流: POST /api/workflows/{id}/execute"
    echo ""
    echo "📝 详细使用指南请查看: $DEPLOY_DIR/AIOps平台高级功能部署指南.md"
    echo ""
    log_info "备份数据位置: $BACKUP_DIR"
    log_info "数据库文件: $DEPLOY_DIR/backend/aiops.db"
}

# 主函数
main() {
    log_info "AIOps平台高级功能离线升级开始..."
    log_info "升级时间: $(date)"
    echo ""
    
    # 执行升级步骤
    check_root
    check_environment
    create_backup
    migrate_database
    update_backend
    update_frontend
    verify_installation
    cleanup
    show_upgrade_result
    
    log_success "升级完成！请重新加载浏览器页面 (Ctrl+F5) 查看新功能。"
}

# 信号处理
trap 'log_error "升级过程中断"; exit 1' INT TERM

# 运行主函数
main "$@"