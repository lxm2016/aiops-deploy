# AIOps平台高级功能离线部署完整指南

> 本指南详细说明如何将现有的AIOps平台升级到包含高级功能的版本，支持完全离线部署

## 📋 功能概述

升级后的平台将包含以下高级功能：

- **🔍 拓扑发现与管理** - 自动发现设备关联关系，支持影响面分析
- **🧠 智能根因分析 (RCA)** - AI驱动的故障定位和解决方案推荐
- **📚 RAG知识库增强** - 智能知识检索和自动学习
- **⚙️ 工作流编排系统** - 可视化工作流设计和自动化执行

---

## 🚀 部署准备

### 1. 环境要求

**服务器要求：**
- 操作系统：CentOS/Rocky/openEuler/Ubuntu 或 Windows Server
- CPU：建议4核以上
- 内存：建议8GB以上
- 存储：100GB以上可用空间
- 网络：完全离线环境

**软件要求：**
- Python 3.9-3.13（已离线部署）
- Nginx（已安装并运行）
- SQLite（已包含）

### 2. 升级前的准备工作

```bash
# 1. 检查当前系统状态
systemctl status aiops-backend
systemctl status nginx

# 2. 创建备份目录
mkdir -p /opt/aiops-deploy/backup

# 3. 备份数据库
cp /opt/aiops-deploy/backend/aiops.db /opt/aiops-deploy/backup/aiops.db.backup_upgrade_$(date +%Y%m%d_%H%M%S)

# 4. 备份配置文件
cp /opt/aiops-deploy/backend/.env /opt/aiops-deploy/backup/.env.backup_upgrade_$(date +%Y%m%d_%H%M%S)

# 5. 确认Python版本
python3 --version  # 应该显示3.9-3.13版本
```

### 3. 获取高级功能升级包

**方式一：使用离线包**
- 从离线存储介质获取 `aiops-advanced-features-YYYYMMDD_HHMMSS.zip`
- 或使用 `offline_package_generator.py` 生成离线包

**方式二：在线生成离线包**
```bash
cd /opt/aiops-deploy
python3 scripts/offline_package_generator.py
```

---

## 🔧 离线部署步骤

### Linux环境部署

#### 第1步：上传并解压部署包
```bash
# 上传部署包到服务器
scp aiops-advanced-features-YYYYMMDD_HHMMSS.zip root@server:/tmp/

# 解压到部署目录
cd /opt
unzip -o /tmp/aiops-advanced-features-YYYYMMDD_HHMMSS.zip -d /tmp/aiops-new
```

#### 第2步：执行升级脚本
```bash
# 赋予执行权限
chmod +x /tmp/aiops-new/scripts/*.sh

# 执行升级脚本
cd /tmp/aiops-new
sudo bash scripts/upgrade_advanced_features.sh
```

#### 第3步：验证升级结果
```bash
# 检查服务状态
systemctl status aiops-backend

# 测试API接口
curl http://localhost:8080/api/health
curl http://localhost:8080/api/topology/discover
curl http://localhost:8080/api/rca/history

# 检查新功能
curl http://localhost:8080/api/knowledge/search?query=服务器
curl http://localhost:8080/api/workflows
```

### Windows环境部署

#### 第1步：解压部署包
- 将 `aiops-advanced-features-YYYYMMDD_HHMMSS.zip` 解压到目标目录（如 `C:\aiops-advanced`）

#### 第2步：执行升级脚本
```cmd
# 以管理员身份运行PowerShell
cd C:\aiops-advanced
scripts\upgrade_advanced_features.bat
```

#### 第3步：验证升级结果
```cmd
# 测试API接口
curl http://localhost:8080/api/health
curl http://localhost:8080/api/topology/discover
```

---

## 📊 功能验证

### 1. 拓扑发现功能测试
```bash
# 1. 触发拓扑发现
curl -X POST http://localhost:8080/api/topology/discover

# 2. 获取拓扑图数据
curl http://localhost:8080/api/topology/graph

# 3. 查看服务器影响面
curl http://localhost:8080/api/topology/server/1/blast-radius

# 4. 查看网络设备影响面
curl http://localhost:8080/api/topology/network/1/blast-radius
```

### 2. 根因分析功能测试
```bash
# 1. 创建测试告警（假设已存在告警）
curl -X POST http://localhost:8080/api/rca/analyze/1

# 2. 查看分析历史
curl http://localhost:8080/api/rca/history?limit=10

# 3. 获取详细分析结果
curl http://localhost:8080/api/rca/1
```

### 3. 知识库功能测试
```bash
# 1. 搜索知识
curl "http://localhost:8080/api/knowledge/search?query=服务器故障&category=solution"

# 2. 添加知识条目
curl -X POST http://localhost:8080/api/knowledge/learn \
  -H "Content-Type: application/json" \
  -d '{"title": "服务器故障处理", "content": "详细内容...", "category": "solution"}'

# 3. 获取相似案例
curl "http://localhost:8080/api/knowledge/similar-incidents?title=服务器宕机&level=critical"
```

### 4. 工作流功能测试
```bash
# 1. 获取工作流模板
curl http://localhost:8080/api/workflows/templates

# 2. 创建工作流
curl -X POST http://localhost:8080/api/workflows \
  -H "Content-Type: application/json" \
  -d '{
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
  }'

# 3. 执行工作流
curl -X POST http://localhost:8080/api/workflows/1/execute
```

---

## 🔒 安全加固

### 1. 配置文件安全
```bash
# 设置配置文件权限
chmod 600 /opt/aiops-deploy/backend/.env

# 生成新的密钥（如需要）
openssl rand -hex 32
```

### 2. 服务文件安全
```bash
# 检查服务文件权限
ls -la /etc/systemd/system/aiops-backend.service

# 设置服务文件权限
chmod 644 /etc/systemd/system/aiops-backend.service
```

### 3. 数据库安全
```bash
# 设置数据库文件权限
chmod 600 /opt/aiops-deploy/backend/aiops.db

# 定期备份脚本
echo '#!/bin/bash
BACKUP_DIR="/opt/aiops-deploy/backup"
DATE=$(date +%Y%m%d_%H%M%S)
cp /opt/aiops-deploy/backend/aiops.db "$BACKUP_DIR/aiops_db_$DATE.db"
find "$BACKUP_DIR" -name "aiops_db_*.db" -mtime +30 -delete
' > /opt/aiops-deploy/scripts/backup_db.sh
chmod +x /opt/aiops-deploy/scripts/backup_db.sh
```

---

## 🔄 版本升级与回滚

### 版本升级
```bash
# 1. 检查当前版本
cat /opt/aiops-deploy/version.txt

# 2. 下载新版本
wget https://github.com/lxm2016/aiops-deploy/archive/main.zip -O /tmp/new_version.zip

# 3. 执行升级
cd /tmp
unzip new_version.zip
bash aiops-deploy-main/scripts/upgrade_advanced_features.sh
```

### 回滚到之前的版本
```bash
# 1. 停止服务
systemctl stop aiops-backend

# 2. 恢复数据库
cp /opt/aiops-deploy/backup/aiops.db.backup_YYYYMMDD_HHMMSS /opt/aiops-deploy/backend/aiops.db

# 3. 恢复配置文件
cp /opt/aiops-deploy/backup/.env.backup_YYYYMMDD_HHMMSS /opt/aiops-deploy/backend/.env

# 4. 重启服务
systemctl start aiops-backend
```

### 紧急回滚
```bash
# 如果升级失败，使用以下命令快速回滚
systemctl stop aiops-backend
cp /opt/aiops-deploy/backup/aiops.db.backup_upgrade_$(date +%Y%m%d) /opt/aiops-deploy/backend/aiops.db
cp /opt/aiops-deploy/backup/.env.backup_upgrade_$(date +%Y%m%d) /opt/aiops-deploy/backend/.env
systemctl start aiops-backend
```

---

## 🔍 故障排查

### 常见问题及解决方案

#### 1. 升级后服务无法启动
```bash
# 检查日志
journalctl -u aiops-backend -n 50

# 检查端口占用
netstat -tlnp | grep 8080

# 重启服务
systemctl restart aiops-backend
```

#### 2. 数据库迁移失败
```bash
# 检查备份文件
ls -la /opt/aiops-deploy/backup/

# 恢复数据库
cp /opt/aiops-deploy/backup/aiops.db.backup_YYYYMMDD_HHMMSS /opt/aiops-deploy/backend/aiops.db

# 重新执行迁移
python3 /opt/aiops-deploy/scripts/migrate_advanced_features.py /opt/aiops-deploy/backend/aiops.db
```

#### 3. API接口无法访问
```bash
# 检查后端服务
curl http://localhost:8080/api/health

# 检查nginx配置
nginx -t
systemctl reload nginx

# 检查防火墙
firewall-cmd --list-ports
```

#### 4. 新功能不可用
```bash
# 检查API接口
curl http://localhost:8080/api/topology/discover
curl http://localhost:8080/api/rca/history

# 检查数据库表
sqlite3 /opt/aiops-deploy/backend/aiops.db ".tables"
sqlite3 /opt/aiops-deploy/backend/aiops.db ".schema topology_relations"
```

---

## 📈 性能优化

### 1. 数据库优化
```bash
# 为新表创建索引
sqlite3 /opt/aiops-deploy/backend/aiops.db "
CREATE INDEX IF NOT EXISTS idx_topology_relations_composite 
ON topology_relations(source_type, source_id, target_type, target_id);

CREATE INDEX IF NOT EXISTS idx_root_cause_analysis_status 
ON root_cause_analysis(status);

CREATE INDEX IF NOT EXISTS idx_knowledge_base_category 
ON knowledge_base(category);
"
```

### 2. 系统优化
```bash
# 增加文件描述符限制
echo '* soft nofile 65536' >> /etc/security/limits.conf
echo '* hard nofile 65536' >> /etc/security/limits.conf

# 优化系统参数
echo 'net.core.somaxconn = 65536' >> /etc/sysctl.conf
echo 'net.ipv4.tcp_max_syn_backlog = 65536' >> /etc/sysctl.conf
sysctl -p
```

### 3. 日志优化
```bash
# 配置日志轮转
cat > /etc/logrotate.d/aiops << EOF
/opt/aiops-deploy/backend/logs/*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    create 644 root root
    postrotate
        systemctl reload aiops-backend
    endscript
}
EOF
```

---

## 📞 技术支持

### 日志收集
```bash
# 收集系统日志
tar -czf /tmp/aiops_logs_$(date +%Y%m%d_%H%M%S).tar.gz \
  /var/log/nginx/ \
  /opt/aiops-deploy/backend/logs/ \
  /tmp/aiops-backend.service.*

# 收集数据库信息
sqlite3 /opt/aiops-deploy/backend/aiops.db ".dump" > /tmp/aiops_db_dump_$(date +%Y%m%d_%H%M%S).sql
```

### 联系信息
- 紧急联系人：管理员
- 技术支持邮箱：support@yourdomain.com
- 问题反馈渠道：内部工单系统

---

## 🎉 总结

通过本指南，您可以成功将现有的AIOps平台升级到包含高级功能的版本。升级后的平台将具备：

- **智能化的运维管理** - 自动发现、自动分析、自动执行
- **可视化的拓扑管理** - 图形化展示设备依赖关系
- **智能化的根因分析** - AI驱动的故障定位
- **自动化的工作流** - 标准化运维流程
- **智能化的知识库** - 基于历史数据的学习和推荐

请按照本指南逐步操作，确保升级过程顺利完成。如有问题，请参考故障排查部分或联系技术支持。

---

*最后更新：2026-09-08*
*版本：1.0.0*