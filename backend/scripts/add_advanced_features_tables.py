#!/usr/bin/env python3
"""
添加高级功能表的数据库迁移脚本
- 拓扑关系表
- 根因分析结果表
- 知识库表
- 工作流定义和执行表
"""
import asyncio
import sys
import os
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from app.core.database import engine, Base
from app.models.models import TopologyRelation, RootCauseAnalysis, KnowledgeBase, WorkflowDefinition, WorkflowExecution

async def migrate_database():
    """添加高级功能表"""
    print("正在添加高级功能表...")
    
    # 创建表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
        # 创建索引
        indexes_sql = [
            "CREATE INDEX IF NOT EXISTS idx_topology_relations_source ON topology_relations(source_type, source_id)",
            "CREATE INDEX IF NOT EXISTS idx_topology_relations_target ON topology_relations(target_type, target_id)",
            "CREATE INDEX IF NOT EXISTS idx_topology_relations_composite ON topology_relations(source_type, source_id, target_type, target_id)",
            "CREATE INDEX IF NOT EXISTS idx_root_cause_analysis_alert ON root_cause_analysis(alert_id)",
            "CREATE INDEX IF NOT EXISTS idx_root_cause_analysis_status ON root_cause_analysis(status)",
            "CREATE INDEX IF NOT EXISTS idx_knowledge_base_category ON knowledge_base(category)",
            "CREATE INDEX IF NOT EXISTS idx_knowledge_base_created ON knowledge_base(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_workflow_definitions_status ON workflow_definitions(status)",
            "CREATE INDEX IF NOT EXISTS idx_workflow_executions_workflow ON workflow_executions(workflow_id)",
            "CREATE INDEX IF NOT EXISTS idx_workflow_executions_status ON workflow_executions(status)",
        ]
        
        for index_sql in indexes_sql:
            try:
                await conn.execute(index_sql)
                print(f"  ✅ 创建索引成功: {index_sql.split('IF NOT EXISTS ')[1].split(' ON')[0]}")
            except Exception as e:
                print(f"  ⚠️  索引已存在或创建失败: {e}")
        
        print("高级功能表创建完成!")
    
    print("\n新增表结构:")
    print("1. TopologyRelation - 设备拓扑关系表")
    print("   - source_type/target_type: server/network/storage/service")
    print("   - relation_type: depends_on/connected_to/hosted_on/monitored_by")
    print("   - strength: 关联强度 (0-1)")
    print("   - metadata: JSON格式的额外信息")
    print()
    print("2. RootCauseAnalysis - 根因分析结果表")
    print("   - analysis_type: topology/correlation/anomaly")
    print("   - confidence_score: 置信度 (0-1)")
    print("   - root_cause: 根因描述")
    print("   - affected_services: 受影响服务列表JSON")
    print("   - recommendations: 建议解决方案")
    print()
    print("3. KnowledgeBase - RAG知识库")
    print("   - category: incident/solution/best_practice/manual")
    print("   - tags: 标签，逗号分隔")
    print("   - relevance_score: 相关性评分")
    print()
    print("4. WorkflowDefinition - 工作流定义")
    print("   - definition: JSON格式的工作流定义")
    print("   - status: active/inactive/draft")
    print()
    print("5. WorkflowExecution - 工作流执行记录")
    print("   - trigger_type: manual/alert/scheduled")
    print("   - progress: 进度百分比")
    print("   - result: 执行结果JSON")

if __name__ == "__main__":
    asyncio.run(migrate_database())