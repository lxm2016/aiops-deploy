#!/usr/bin/env python3
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
        
        return True
    
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