# AIOps 平台高级功能部署指南

## 📋 功能概述

基于 Ongrid 项目的先进理念，我们为您的 AIOps 平台增加了以下高级功能：

### 🔍 1. 拓扑发现与管理
- **自动拓扑发现**：自动发现服务器、网络设备、存储之间的关联关系
- **拓扑可视化**：图形化展示设备依赖关系
- **影响面分析**：快速计算设备故障的影响范围
- **手动关系管理**：支持手动配置和编辑拓扑关系

### 🧠 2. 智能根因分析 (RCA)
- **多维度分析**：拓扑分析、相关性分析、异常检测
- **AI驱动分析**：集成千问大模型进行智能分析
- **自动调查**：告警触发自动根因调查流程
- **历史案例匹配**：基于历史案例提供解决建议

### 📚 3. RAG 知识库增强
- **智能搜索**：支持全文检索和分类过滤
- **自动学习**：从故障案例中自动提取知识
- **相似案例推荐**：推荐相似的故障处理方案
- **知识管理**：结构化存储运维知识和最佳实践

### ⚙️ 4. 工作流编排系统
- **可视化流程编辑**：拖拽式工作流设计器
- **多种执行模式**：手动触发、告警触发、定时触发
- **丰富的步骤类型**：等待、动作、条件、通知、并行执行等
- **执行状态监控**：实时跟踪工作流执行状态

## 🚀 部署步骤

### 第1步：更新数据库结构

运行数据库迁移脚本，添加新的数据表：

```bash
# 进入后端目录
cd /opt/aiops-deploy/backend

# 执行数据库迁移
python scripts/add_advanced_features_tables.py
```

### 第2步：更新后端服务

1. **重启后端服务**：
```bash
systemctl restart aiops-backend
```

2. **检查服务状态**：
```bash
systemctl status aiops-backend
```

### 第3步：验证功能可用性

#### 3.1 拓扑发现功能
```bash
# API 测试
curl -X POST http://localhost:8000/api/topology/discover
curl -X GET http://localhost:8000/api/topology/graph
curl -X GET http://localhost:8000/api/topology/server_1/1/blast-radius
```

#### 3.2 根因分析功能
```bash
# 创建测试告警并分析
curl -X POST http://localhost:8000/api/rca/analyze/1
curl -X GET http://localhost:8000/api/rca/history
```

#### 3.3 知识库功能
```bash
# 添加知识条目
curl -X POST http://localhost:8000/api/knowledge/learn \
  -H "Content-Type: application/json" \
  -d '{"title": "服务器故障处理", "content": "详细内容...", "category": "solution"}'

# 搜索知识库
curl "http://localhost:8000/api/knowledge/search?query=服务器"
```

#### 3.4 工作流功能
```bash
# 获取工作流模板
curl http://localhost:8000/api/workflows/templates

# 创建工作流
curl -X POST http://localhost:8000/api/workflows \
  -H "Content-Type: application/json" \
  -d '{"name": "服务器重启", "description": "标准重启流程", "definition": {...}}'

# 执行工作流
curl -X POST http://localhost:8000/api/workflows/1/execute
```

## 🔧 API 接口详解

### 拓扑管理 API

#### 自动发现拓扑
```http
POST /api/topology/discover
```
触发自动拓扑发现，分析设备之间的关联关系。

#### 获取拓扑图
```http
GET /api/topology/graph?device_type=server&device_id=1
```
获取拓扑关系图数据，支持按设备过滤。

#### 影响面分析
```http
GET /api/topology/{device_type}/{device_id}/blast-radius
```
计算指定设备故障的影响范围和依赖路径。

### 根因分析 API

#### 启动分析
```http
POST /api/rca/analyze/{alert_id}
```
对指定告警进行根因分析。

#### 查看历史
```http
GET /api/rca/history?limit=10
```
获取根因分析历史记录。

#### 获取详情
```http
GET /api/rca/{analysis_id}
```
查看根因分析的详细结果。

### 知识库 API

#### 搜索知识
```http
GET /api/knowledge/search?query=关键词&category=solution&limit=10
```
搜索知识库内容。

#### 从故障学习
```http
POST /api/knowledge/learn-from-incident/{incident_id}
```
从故障案例中提取知识。

#### 获取相似案例
```http
GET /api/knowledge/similar-incidents?title=故障标题&level=critical&limit=5
```

#### 解决方案推荐
```http
GET /api/knowledge/solutions?alert_id=123
```

### 工作流 API

#### 获取工作流列表
```http
GET /api/workflows
```

#### 创建工作流
```http
POST /api/workflows
Content-Type: application/json

{
  "name": "服务器重启流程",
  "description": "标准的服务器重启流程",
  "definition": {
    "steps": [
      {
        "type": "action",
        "name": "通知",
        "action": "send_notification",
        "parameters": {
          "channel": "slack",
          "message": "服务器即将重启",
          "recipients": ["team"]
        }
      },
      {
        "type": "delay",
        "name": "等待",
        "delay_seconds": 30
      },
      {
        "type": "action",
        "name": "重启",
        "action": "execute_command",
        "parameters": {
          "command": "sudo reboot",
          "timeout": 60
        }
      }
    ]
  }
}
```

#### 执行工作流
```http
POST /api/workflows/{workflow_id}/execute
Content-Type: application/json

{
  "trigger_data": {
    "alert_id": 123,
    "severity": "critical"
  }
}
```

## 🎯 使用场景

### 场景1：服务器故障处理
1. **告警触发**：服务器宕机告警
2. **自动分析**：系统自动触发根因分析
3. **影响评估**：计算故障影响的服务和业务
4. **解决方案**：基于知识库推荐处理方案
5. **自动执行**：启动标准化的故障处理工作流

### 场景2：网络故障排查
1. **拓扑分析**：自动定位网络故障路径
2. **关联告警**：发现相关的网络设备告警
3. **影响面评估**：确定受影响的业务系统
4. **专家建议**：提供网络优化建议
5. **自动修复**：执行网络配置恢复工作流

### 场景3：容量规划
1. **性能分析**：分析历史性能数据
2. **趋势预测**：预测资源使用趋势
3. **建议生成**：自动生成扩容建议
4. **规划工作流**：启动扩容规划流程

## 📊 性能优化建议

### 1. 数据库优化
```sql
-- 为拓扑关系表创建复合索引
CREATE INDEX idx_topology_relations_composite ON topology_relations(source_type, source_id, target_type, target_id);

-- 为根因分析表创建索引
CREATE INDEX idx_root_cause_analysis_alert ON root_cause_analysis(alert_id);
CREATE INDEX idx_root_cause_analysis_status ON root_cause_analysis(status);

-- 为知识库表创建索引
CREATE INDEX idx_knowledge_base_category ON knowledge_base(category);
CREATE INDEX idx_knowledge_base_created ON knowledge_base(created_at);
```

### 2. 消息队列
考虑使用 Redis 或 RabbitMQ 来处理工作流的异步执行：

```python
# 工作流执行队列
def enqueue_workflow_execution(workflow_id, trigger_data):
    # 将工作流任务加入队列
    pass
```

### 3. 缓存策略
```python
# 缓存拓扑数据
cache.set(f"topology_graph_{device_type}_{device_id}", graph_data, timeout=3600)

# 缓存知识库搜索结果
cache.set(f"knowledge_search_{query}_{category}", search_results, timeout=1800)
```

## 🔒 安全配置

### 1. API 访问控制
```python
# 工作流执行权限验证
@router.post("/workflows/{workflow_id}/execute")
async def execute_workflow(workflow_id: int, request: Request):
    # 验证用户权限
    user = await get_current_user(request)
    if not user.has_permission("workflow.execute"):
        raise HTTPException(status_code=403, detail="Permission denied")
    
    # 执行工作流
    pass
```

### 2. 数据敏感信息
```python
# 敏感信息脱敏
def mask_sensitive_data(data):
    if "password" in data:
        data["password"] = "***"
    if "token" in data:
        data["token"] = "***"
    return data
```

## 📈 监控和运维

### 1. 功能监控
```python
# 监控拓扑发现成功率
monitoring.gauge("topology_discovery_success_rate", success_rate)

# 监控根因分析准确率
monitoring.gauge("rca_accuracy", accuracy_score)

# 监控工作流执行状态
monitoring.counter("workflow_executions_total", {"status": "success"})
```

### 2. 性能监控
```python
# 监控API响应时间
@monitoring.time("api_response_time")
async def api_handler():
    # API处理逻辑
    pass
```

### 3. 错误处理
```python
# 统一错误处理
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"API error: {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error"}
    )
```

## 🔄 版本升级

### 从旧版本升级
1. **备份数据库**
```bash
sqlite3 aiops.db ".backup backup_$(date +%Y%m%d).db"
```

2. **运行迁移脚本**
```bash
python scripts/add_advanced_features_tables.py
```

3. **重启服务**
```bash
systemctl restart aiops-backend
systemctl restart aiops-frontend
```

### 版本兼容性
- 新版本向后兼容，不影响现有功能
- 新功能可选启用，不影响原有业务流程
- 支持渐进式升级，可逐步启用新功能

## 📞 技术支持

如遇到问题，请检查：
1. 服务日志：`journalctl -u aiops-backend -f`
2. 数据库连接：`sqlite3 aiops.db "SELECT COUNT(*) FROM users;"`
3. 网络连接：`curl http://localhost:8000/health`
4. 权限配置：检查API访问权限和数据库权限

---

## 🎉 总结

通过这些高级功能的引入，您的 AIOps 平台现在具备了：

- **智能化的故障处理**：自动分析、自动学习、自动执行
- **可视化的运维管理**：拓扑图、工作流、性能监控
- **标准化的操作流程**：减少人为错误，提高处理效率
- **知识驱动的决策支持**：基于历史数据提供最佳实践

这将显著提升您的运维效率和故障处理能力，让您的团队从被动响应转变为主动预防！