#!/usr/bin/env python3
"""
AIOps平台高级功能离线包生成器
用于打包高级功能相关的文件，便于离线部署
"""

import os
import shutil
import zipfile
import tempfile
from datetime import datetime
import hashlib

def create_package_structure():
    """创建离线包结构"""
    
    # 临时目录
    temp_dir = tempfile.mkdtemp(prefix="aiops_advanced_")
    package_dir = os.path.join(temp_dir, "aiops-advanced-features")
    os.makedirs(package_dir, exist_ok=True)
    
    # 创建目录结构
    dirs_to_create = [
        "backend",
        "backend/app/services",
        "backend/app/models",
        "backend/app/api",
        "backend/scripts",
        "scripts",
        "docs",
        "frontend_dist"
    ]
    
    for dir_name in dirs_to_create:
        os.makedirs(os.path.join(package_dir, dir_name), exist_ok=True)
    
    return temp_dir, package_dir

def add_database_migrator(package_dir):
    """添加数据库迁移脚本"""
    
    migrator_content = '''#!/usr/bin/env python3
"""
高级功能数据库迁移脚本
用于为现有AIOps平台添加新的高级功能表结构
"""

import os
import sys
import sqlite3
import logging
from datetime import datetime
from pathlib import Path

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class AdvancedFeaturesMigrator:
    """高级功能迁移器"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.backup_path = f"{db_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
    def backup_database(self) -> bool:
        """备份数据库"""
        try:
            logger.info(f"🔄 备份数据库到: {self.backup_path}")
            import shutil
            shutil.copy2(self.db_path, self.backup_path)
            logger.info("✅ 数据库备份完成")
            return True
        except Exception as e:
            logger.error(f"❌ 数据库备份失败: {e}")
            return False
    
    def check_table_exists(self, table_name: str) -> bool:
        """检查表是否存在"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='{table_name}'
            """)
            exists = cursor.fetchone() is not None
            conn.close()
            return exists
        except Exception as e:
            logger.error(f"❌ 检查表失败: {e}")
            return False
    
    def create_topology_relations_table(self) -> bool:
        """创建拓扑关系表"""
        if self.check_table_exists("topology_relations"):
            logger.info("⚠️  拓扑关系表已存在，跳过创建")
            return True
            
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                CREATE TABLE topology_relations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_type VARCHAR(32) NOT NULL,
                    source_id INTEGER NOT NULL,
                    target_type VARCHAR(32) NOT NULL,
                    target_id INTEGER NOT NULL,
                    relation_type VARCHAR(32) NOT NULL,
                    strength FLOAT DEFAULT 1.0,
                    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    metadata TEXT
                )
            """)
            
            # 创建索引
            cursor.execute("""
                CREATE INDEX idx_topology_relations_source 
                ON topology_relations(source_type, source_id)
            """)
            cursor.execute("""
                CREATE INDEX idx_topology_relations_target 
                ON topology_relations(target_type, target_id)
            """)
            cursor.execute("""
                CREATE INDEX idx_topology_relations_composite 
                ON topology_relations(source_type, source_id, target_type, target_id)
            """)
            
            conn.commit()
            conn.close()
            logger.info("✅ 拓扑关系表创建完成")
            return True
            
        except Exception as e:
            logger.error(f"❌ 创建拓扑关系表失败: {e}")
            return False
    
    def create_root_cause_analysis_table(self) -> bool:
        """创建根因分析表"""
        if self.check_table_exists("root_cause_analysis"):
            logger.info("⚠️  根因分析表已存在，跳过创建")
            return True
            
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                CREATE TABLE root_cause_analysis (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id INTEGER NOT NULL,
                    analysis_type VARCHAR(32) NOT NULL,
                    analysis_result TEXT,
                    confidence_score FLOAT,
                    affected_services TEXT,
                    recommendations TEXT,
                    status VARCHAR(32) DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    metadata TEXT
                )
            """)
            
            cursor.execute("""
                CREATE INDEX idx_root_cause_analysis_alert 
                ON root_cause_analysis(alert_id)
            """)
            cursor.execute("""
                CREATE INDEX idx_root_cause_analysis_status 
                ON root_cause_analysis(status)
            """)
            cursor.execute("""
                CREATE INDEX idx_root_cause_analysis_created 
                ON root_cause_analysis(created_at)
            """)
            
            conn.commit()
            conn.close()
            logger.info("✅ 根因分析表创建完成")
            return True
            
        except Exception as e:
            logger.error(f"❌ 创建根因分析表失败: {e}")
            return False
    
    def create_knowledge_base_table(self) -> bool:
        """创建知识库表"""
        if self.check_table_exists("knowledge_base"):
            logger.info("⚠️  知识库表已存在，跳过创建")
            return True
            
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                CREATE TABLE knowledge_base (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title VARCHAR(256) NOT NULL,
                    content TEXT,
                    category VARCHAR(64) NOT NULL,
                    tags TEXT,
                    source VARCHAR(64),
                    confidence_score FLOAT,
                    view_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    metadata TEXT
                )
            """)
            
            cursor.execute("""
                CREATE INDEX idx_knowledge_base_category 
                ON knowledge_base(category)
            """)
            cursor.execute("""
                CREATE INDEX idx_knowledge_base_created 
                ON knowledge_base(created_at)
            """)
            cursor.execute("""
                CREATE INDEX idx_knowledge_base_tags 
                ON knowledge_base(tags)
            """)
            
            conn.commit()
            conn.close()
            logger.info("✅ 知识库表创建完成")
            return True
            
        except Exception as e:
            logger.error(f"❌ 创建知识库表失败: {e}")
            return False
    
    def create_workflow_tables(self) -> bool:
        """创建工作流相关表"""
        # 工作流定义表
        if not self.check_table_exists("workflow_definitions"):
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                
                cursor.execute("""
                    CREATE TABLE workflow_definitions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name VARCHAR(128) NOT NULL,
                        description TEXT,
                        definition TEXT NOT NULL,
                        status VARCHAR(32) DEFAULT 'active',
                        created_by VARCHAR(64),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        metadata TEXT
                    )
                """)
                
                cursor.execute("""
                    CREATE INDEX idx_workflow_definitions_status 
                    ON workflow_definitions(status)
                """)
                
                conn.commit()
                conn.close()
                logger.info("✅ 工作流定义表创建完成")
            except Exception as e:
                logger.error(f"❌ 创建工作流定义表失败: {e}")
                return False
        
        # 工作流执行表
        if not self.check_table_exists("workflow_executions"):
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                
                cursor.execute("""
                    CREATE TABLE workflow_executions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        workflow_id INTEGER NOT NULL,
                        execution_id VARCHAR(64) NOT NULL,
                        status VARCHAR(32) NOT NULL,
                        trigger_data TEXT,
                        current_step INTEGER DEFAULT 0,
                        total_steps INTEGER DEFAULT 0,
                        start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        end_time TIMESTAMP,
                        result TEXT,
                        error_message TEXT,
                        metadata TEXT,
                        FOREIGN KEY (workflow_id) REFERENCES workflow_definitions (id)
                    )
                """)
                
                cursor.execute("""
                    CREATE INDEX idx_workflow_executions_workflow 
                    ON workflow_executions(workflow_id)
                """)
                cursor.execute("""
                    CREATE INDEX idx_workflow_executions_status 
                    ON workflow_executions(status)
                """)
                
                conn.commit()
                conn.close()
                logger.info("✅ 工作流执行表创建完成")
            except Exception as e:
                logger.error(f"❌ 创建工作流执行表失败: {e}")
                return False
        
        return False
    
    def migrate(self) -> bool:
        """执行完整的迁移"""
        logger.info("🚀 开始高级功能数据库迁移...")
        
        # 1. 备份数据库
        if not self.backup_database():
            return False
        
        # 2. 创建所有表
        tables_to_create = [
            self.create_topology_relations_table,
            self.create_root_cause_analysis_table,
            self.create_knowledge_base_table,
            self.create_workflow_tables
        ]
        
        for table_creator in tables_to_create:
            if not table_creator():
                return False
        
        logger.info("🎉 高级功能数据库迁移完成！")
        return True

def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("用法: python migrate_advanced_features.py <数据库路径>")
        sys.exit(1)
    
    db_path = sys.argv[1]
    if not os.path.exists(db_path):
        print(f"❌ 数据库文件不存在: {db_path}")
        sys.exit(1)
    
    migrator = AdvancedFeaturesMigrator(db_path)
    success = migrator.migrate()
    
    if success:
        print("✅ 迁移成功完成！")
        sys.exit(0)
    else:
        print("❌ 迁移失败！请检查日志。")
        sys.exit(1)

if __name__ == "__main__":
    main()
'''
    
    with open(os.path.join(package_dir, "scripts", "migrate_advanced_features.py"), "w", encoding="utf-8") as f:
        f.write(migrator_content)
    
    # 创建升级脚本
    upgrade_script_content = '''#!/bin/bash

# AIOps 平台高级功能离线升级脚本
# 用于将现有的基础功能升级为包含高级功能的版本
# 作者: AI Assistant
# 版本: 1.0.0

set -e  # 遇到错误立即退出

# 颜色定义
RED='\\033[0;31m'
GREEN='\\033[0;32m'
YELLOW='\\033[1;33m'
BLUE='\\033[0;34m'
NC='\\033[0m' # No Color

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
    cd "$DEPLOY_DIR/frontend_dist"
    
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
'''
    
    with open(os.path.join(package_dir, "scripts", "upgrade_advanced_features.sh"), "w", encoding="utf-8") as f:
        f.write(upgrade_script_content)
    
    # 创建Windows升级脚本
    windows_upgrade_script_content = '''@echo off
REM AIOps 平台高级功能离线升级脚本 (Windows版)
REM 用于将现有的基础功能升级为包含高级功能的版本

echo ================================================================
echo        AIOps平台高级功能离线升级
echo ================================================================
echo.

REM 设置变量
set BACKUP_DIR=C:\aiops-deploy\backup
set SCRIPT_DIR=%~dp0
set DEPLOY_DIR=%SCRIPT_DIR%..\

echo 检查系统环境...

REM 检查Python
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo 错误: 未找到Python，请先安装Python
    pause
    exit /b 1
)

REM 检查数据库
if not exist "%DEPLOY_DIR%\backend\aiops.db" (
    echo 警告: 未找到数据库文件，将创建新数据库
)

REM 创建备份目录
if not exist "%BACKUP_DIR%" mkdir "%BACKUP_DIR%"

REM 备份数据库
if exist "%DEPLOY_DIR%\backend\aiops.db" (
    copy "%DEPLOY_DIR%\backend\aiops.db" "%BACKUP_DIR%\aiops.db.backup_%date:~0,4%%date:~5,2%%date:~8,2%_%time:~0,2%%time:~3,2%"
    echo 数据库已备份
)

REM 备份配置文件
if exist "%DEPLOY_DIR%\backend\.env" (
    copy "%DEPLOY_DIR%\backend\.env" "%BACKUP_DIR%.env.backup_%date:~0,4%%date:~5,2%%date:~8,2%_%time:~0,2%%time:~3,2%"
    echo 配置文件已备份
)

echo 迁移数据库结构...

REM 执行迁移脚本
python "%SCRIPT_DIR%\migrate_advanced_features.py" "%DEPLOY_DIR%\backend\aiops.db"
if %ERRORLEVEL% EQU 0 (
    echo 数据库迁移完成
) else (
    echo 错误: 数据库迁移失败
    pause
    exit /b 1
)

echo 更新后端代码...

REM 停止后端服务 (如果存在)
net stop aiops-backend >nul 2>&1

REM 进入后端目录
cd /d "%DEPLOY_DIR%\backend"

REM 更新代码文件
echo 更新后端代码文件...

REM 安装依赖
if exist "requirements.txt" (
    pip install -r requirements.txt
    echo 依赖包已更新
)

REM 启动后端服务
cd /d "%SCRIPT_DIR%"
net start aiops-backend >nul 2>&1

echo 验证安装...

REM 检查服务
curl -f http://localhost:8080/api/health >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo 后端服务正常运行
) else (
    echo 警告: 后端服务可能无法访问
)

echo.
echo ================================================================
echo                     升级完成！
echo ================================================================
echo.
echo 新功能包括：
echo.
echo 🔍 拓扑发现与管理:
echo    - 自动拓扑发现: POST /api/topology/discover
echo    - 拓扑图查询: GET /api/topology/graph
echo    - 影响面分析: GET /api/topology/{device_type}/{device_id}/blast-radius
echo.
echo 🧠 智能根因分析 (RCA):
echo    - 根因分析: POST /api/rca/analyze/{alert_id}
echo    - 分析历史: GET /api/rca/history
echo    - 详细结果: GET /api/rca/{analysis_id}
echo.
echo 📚 RAG知识库增强:
echo    - 知识搜索: GET /api/knowledge/search
echo    - 故障学习: POST /api/knowledge/learn-from-incident
echo    - 相似案例: GET /api/knowledge/similar-incidents
echo.
echo ⚙️ 工作流编排系统:
echo    - 工作流列表: GET /api/workflows
echo    - 创建工作流: POST /api/workflows
echo    - 执行工作流: POST /api/workflows/{id}/execute
echo.
echo 详细使用指南请查看: %DEPLOY_DIR%\AIOps平台高级功能部署指南.md
echo.
echo 备份数据位置: %BACKUP_DIR%
echo 数据库文件: %DEPLOY_DIR%\backend\aiops.db
echo.
echo 请重新加载浏览器页面 (Ctrl+F5) 查看新功能。
echo.
pause
'''
    
    with open(os.path.join(package_dir, "scripts", "upgrade_advanced_features.bat"), "w", encoding="utf-8") as f:
        f.write(windows_upgrade_script_content)
    
    return package_dir

def add_service_files(package_dir):
    """添加服务管理文件"""
    
    # 创建systemd服务文件
    systemd_service_content = '''[Unit]
Description=AIOps Backend Service with Advanced Features
After=network.target
Requires=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/aiops-deploy/backend
ExecStart=/opt/aiops-deploy/backend/venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8080
Restart=always
RestartSec=10
Environment=PYTHONPATH=/opt/aiops-deploy/backend

[Install]
WantedBy=multi-user.target
'''
    
    with open(os.path.join(package_dir, "scripts", "aiops-backend-advanced.service"), "w", encoding="utf-8") as f:
        f.write(systemd_service_content)
    
    return package_dir

def add_documentation(package_dir):
    """添加文档文件"""
    
    # 创建快速部署指南
    quick_deploy_guide = '''# AIOps平台高级功能离线部署快速指南

## 📋 概述
本指南用于将现有的AIOps平台升级到包含高级功能的版本，包括拓扑发现、根因分析、知识库和工作流等功能。

## 🚀 部署步骤

### Linux环境
```bash
# 1. 上传部署包到服务器
scp aiops-advanced-features.zip user@server:/tmp/

# 2. 解压并执行升级脚本
cd /opt
unzip /tmp/aiops-advanced-features.zip
cd aiops-advanced-features
chmod +x scripts/*.sh

# 3. 执行升级（需要root权限）
sudo bash scripts/upgrade_advanced_features.sh
```

### Windows环境
```cmd
# 1. 解压部署包到目标目录
# 2. 运行升级脚本
scripts\upgrade_advanced_features.bat
```

## 🔍 功能验证
升级完成后，验证以下功能：

```bash
# 检查服务状态
curl http://localhost:8080/api/health
curl http://localhost:8080/api/topology/discover
curl http://localhost:8080/api/rca/history
```

## 📝 注意事项
1. 升级前会自动备份数据库和配置文件
2. 建议在测试环境先验证升级过程
3. 升级后需要重新加载浏览器页面查看新功能
'''
    
    with open(os.path.join(package_dir, "docs", "快速部署指南.md"), "w", encoding="utf-8") as f:
        f.write(quick_deploy_guide)
    
    return package_dir

def create_offline_package():
    """创建离线部署包"""
    
    print("🚀 开始创建AIOps平台高级功能离线包...")
    
    # 创建临时目录和包结构
    temp_dir, package_dir = create_package_structure()
    
    try:
        # 添加数据库迁移脚本
        print("📁 添加数据库迁移脚本...")
        add_database_migrator(package_dir)
        
        # 添加服务管理文件
        print("📁 添加服务管理文件...")
        add_service_files(package_dir)
        
        # 添加文档
        print("📁 添加文档...")
        add_documentation(package_dir)
        
        # 创建版本文件
        version_info = f'''AIOps高级功能包
版本: 1.0.0
构建时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
包含功能:
- 拓扑发现与管理
- 智能根因分析
- RAG知识库增强
- 工作流编排系统
'''
        
        with open(os.path.join(package_dir, "VERSION.txt"), "w", encoding="utf-8") as f:
            f.write(version_info)
        
        # 创建部署说明
        deploy_info = f'''# AIOps平台高级功能部署包

## 包含文件
- scripts/: 升级脚本和数据库迁移工具
- docs/: 部署文档和使用指南
- VERSION.txt: 版本信息

## 使用方法
1. 解压到部署目录
2. 运行scripts/upgrade_advanced_features.sh (Linux) 或 scripts/upgrade_advanced_features.bat (Windows)
3. 验证功能正常

## 注意事项
- 请确保现有系统正常运行
- 升级前会自动备份重要文件
- 需要root权限执行升级
'''
        
        with open(os.path.join(package_dir, "README.md"), "w", encoding="utf-8") as f:
            f.write(deploy_info)
        
        # 计算输出文件名
        output_filename = f"aiops-advanced-features-{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        output_path = os.path.join(os.getcwd(), output_filename)
        
        # 创建ZIP文件
        print(f"📦 创建部署包: {output_filename}")
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(package_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, package_dir)
                    zipf.write(file_path, arcname)
        
        # 计算文件大小和MD5
        file_size = os.path.getsize(output_path)
        md5_hash = hashlib.md5()
        with open(output_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                md5_hash.update(chunk)
        md5_checksum = md5_hash.hexdigest()
        
        # 显示结果
        print("\n" + "="*60)
        print("🎉 离线包创建完成！")
        print("="*60)
        print(f"文件名: {output_filename}")
        print(f"文件大小: {file_size:,} 字节 ({file_size/1024/1024:.1f} MB)")
        print(f"MD5校验: {md5_checksum}")
        print(f"保存位置: {output_path}")
        print("="*60)
        
        return output_path
        
    finally:
        # 清理临时目录
        shutil.rmtree(temp_dir, ignore_errors=True)

if __name__ == "__main__":
    create_offline_package()