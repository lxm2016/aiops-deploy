"""RAG知识库服务"""
from typing import List, Dict, Any, Optional
from datetime import datetime
from sqlalchemy import and_, func, select, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models import KnowledgeBase, Alert, RootCauseAnalysis, Server, NetworkDevice
from app.services.llm_service import chat_completion
import re


class KnowledgeService:
    """知识库服务"""
    
    @staticmethod
    async def search_knowledge(
        query: str,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 10
    ) -> Dict[str, Any]:
        """搜索知识库"""
        db = AsyncSessionLocal()
        
        try:
            # 构建查询条件
            conditions = []
            
            # 全文搜索标题和内容
            conditions.append(
                or_(
                    KnowledgeBase.title.ilike(f"%{query}%"),
                    KnowledgeBase.content.ilike(f"%{query}%"),
                    KnowledgeBase.tags.ilike(f"%{query}%")
                )
            )
            
            # 分类过滤
            if category:
                conditions.append(KnowledgeBase.category == category)
            
            # 标签过滤
            if tags:
                for tag in tags:
                    conditions.append(KnowledgeBase.tags.ilike(f"%{tag}%"))
            
            # 执行查询
            query = select(KnowledgeBase).where(and_(*conditions))
            result = await db.execute(query.order_by(desc(KnowledgeBase.relevance_score), desc(KnowledgeBase.created_at)))
            knowledge_items = result.scalars().all()
            
            # 计算相关性分数并排序
            scored_items = []
            for item in knowledge_items[:limit]:
                score = KnowledgeService._calculate_relevance_score(item, query)
                scored_items.append({
                    "id": item.id,
                    "title": item.title,
                    "content": item.content,
                    "category": item.category,
                    "tags": item.tags.split(",") if item.tags else [],
                    "source": item.source,
                    "relevance_score": score,
                    "created_at": item.created_at.isoformat(),
                    "snippet": KnowledgeService._generate_snippet(item.content, query)
                })
            
            # 按相关性排序
            scored_items.sort(key=lambda x: x["relevance_score"], reverse=True)
            
            return {
                "query": query,
                "results": scored_items,
                "total": len(scored_items),
                "categories": list(set([k.category for k in knowledge_items])),
                "tags": list(set(tag for k in knowledge_items for tag in (k.tags.split(",") if k.tags else [])))
            }
            
        finally:
            await db.close()
    
    @staticmethod
    async def add_knowledge(
        title: str,
        content: str,
        category: str,
        tags: Optional[str] = None,
        source: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """添加知识库条目"""
        db = AsyncSessionLocal()
        
        try:
            # 验证分类
            valid_categories = ["incident", "solution", "best_practice", "manual"]
            if category not in valid_categories:
                return {"error": f"Invalid category. Must be one of: {valid_categories}"}
            
            # 计算相关性分数
            relevance_score = KnowledgeService._calculate_content_relevance(content)
            
            # 创建知识条目
            knowledge_item = KnowledgeBase(
                title=title,
                content=content,
                category=category,
                tags=tags or "",
                source=source or "manual",
                relevance_score=relevance_score
            )
            
            db.add(knowledge_item)
            await db.commit()
            
            return {
                "success": True,
                "id": knowledge_item.id,
                "title": title,
                "category": category,
                "tags": tags.split(",") if tags else [],
                "relevance_score": relevance_score,
                "created_at": knowledge_item.created_at.isoformat()
            }
            
        except Exception as e:
            await db.rollback()
            return {"error": str(e)}
        finally:
            await db.close()
    
    @staticmethod
    async def learn_from_incident(incident_id: int) -> Dict[str, Any]:
        """从故障案例中学习并自动添加到知识库"""
        db = AsyncSessionLocal()
        
        try:
            # 获取告警和根因分析
            alert_result = await db.execute(select(Alert).where(Alert.id == incident_id))
            alert = alert_result.scalar_one_or_none()
            
            if not alert:
                return {"error": "Incident not found"}
            
            # 获取相关的根因分析
            rca_result = await db.execute(
                select(RootCauseAnalysis).where(RootCauseAnalysis.alert_id == incident_id)
            )
            rca = rca_result.scalar_one_or_none()
            
            # 生成知识条目
            title = f"[{alert.level.upper()}] {alert.title} - 故障分析"
            
            content = f"""
## 故障概述
- **告警源**: {alert.source}
- **告警级别**: {alert.level}
- **发生时间**: {alert.created_at}
- **故障标题**: {alert.title}

## 根因分析
{rca.root_cause if rca else "待分析"}

### 影响范围
{rca.affected_services if rca else "待确认"}

### 修复建议
{rca.recommendations if rca else "待补充"}

## 处理过程
- 发现时间: {alert.created_at}
- 处理状态: 已解决
- 经验教训: 基于本次故障的分析和解决过程总结

## 预防措施
1. 加强监控，提前预警类似问题
2. 优化相关配置和参数
3. 建立标准化的处理流程
4. 定期进行系统健康检查

## 相关文档
- 监控配置文档
- 故障处理手册
- 最佳实践指南
"""
            
            # 添加到知识库
            knowledge_item = KnowledgeBase(
                title=title,
                content=content,
                category="incident",
                tags=f"故障分析,{alert.level.lower()},监控告警",
                source="auto_learn",
                relevance_score=0.9
            )
            
            db.add(knowledge_item)
            await db.commit()
            
            return {
                "success": True,
                "id": knowledge_item.id,
                "title": title,
                "category": "incident",
                "learned_from": incident_id,
                "created_at": knowledge_item.created_at.isoformat()
            }
            
        except Exception as e:
            await db.rollback()
            return {"error": str(e)}
        finally:
            await db.close()
    
    @staticmethod
    async def get_similar_incidents(
        current_incident: Dict[str, Any],
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """查找相似的历史故障案例"""
        db = AsyncSessionLocal()
        
        try:
            # 提取关键信息
            alert_title = current_incident.get("title", "")
            alert_level = current_incident.get("level", "")
            alert_source = current_incident.get("source", "")
            
            # 搜索相似的故障案例
            conditions = [
                KnowledgeBase.category == "incident",
                KnowledgeBase.content.ilike(f"%{alert_title}%")
            ]
            
            if alert_level:
                conditions.append(KnowledgeBase.tags.ilike(f"%{alert_level.lower()}%"))
            
            if alert_source:
                conditions.append(KnowledgeBase.tags.ilike(f"%{alert_source}%"))
            
            result = await db.execute(
                select(KnowledgeBase)
                .where(and_(*conditions))
                .order_by(desc(KnowledgeBase.relevance_score))
                .limit(limit)
            )
            
            similar_incidents = result.scalars().all()
            
            incidents = []
            for incident in similar_incidents:
                incidents.append({
                    "id": incident.id,
                    "title": incident.title,
                    "content": incident.content,
                    "relevance_score": incident.relevance_score,
                    "created_at": incident.created_at.isoformat(),
                    "snippet": KnowledgeService._generate_snippet(incident.content, alert_title)
                })
            
            return incidents
            
        finally:
            await db.close()
    
    @staticmethod
    async def generate_solution_recommendations(incident: Alert) -> Dict[str, Any]:
        """基于历史案例生成解决方案建议"""
        db = AsyncSessionLocal()
        
        try:
            # 查找相似的解决方案
            solutions_result = await db.execute(
                select(KnowledgeBase).where(
                    and_(
                        KnowledgeBase.category == "solution",
                        KnowledgeBase.content.ilike(f"%{incident.title}%")
                    )
                )
            )
            solutions = solutions_result.scalars().all()
            
            recommendations = []
            for solution in solutions[:3]:
                recommendations.append({
                    "title": solution.title,
                    "content": solution.content,
                    "relevance": solution.relevance_score,
                    "snippet": KnowledgeService._generate_snippet(solution.content, incident.title)
                })
            
            # 使用AI生成个性化建议
            context = f"""
当前告警:
- 级别: {incident.level}
- 源: {incident.source}
- 标题: {incident.title}

相似解决方案:
{chr(10).join([f"{i+1}. {s['title']}" for i, s in enumerate(recommendations)])}
"""
            
            prompt = f"""基于当前告警和相似的历史解决方案，请生成具体的处理建议。

{context}

请提供：
1. 立即处理步骤（优先级排序）
2. 问题排查方向
3. 长期解决方案
4. 预防措施

使用Markdown格式，重点突出处理步骤和解决方案。"""
            
            ai_recommendations = await chat_completion(prompt, session_id="solution_recommendations")
            
            return {
                "immediate_actions": recommendations[:2],
                "ai_recommendations": ai_recommendations,
                "similar_solutions": len(recommendations),
                "generated_at": datetime.utcnow().isoformat()
            }
            
        finally:
            await db.close()
    
    @staticmethod
    def _calculate_relevance_score(knowledge_item: KnowledgeBase, query: str) -> float:
        """计算知识条目与查询的相关性分数"""
        score = 0.0
        
        # 标题匹配权重最高
        if query.lower() in knowledge_item.title.lower():
            score += 0.5
        
        # 内容匹配
        if query.lower() in knowledge_item.content.lower():
            score += 0.3
        
        # 标签匹配
        if knowledge_item.tags and query.lower() in knowledge_item.tags.lower():
            score += 0.2
        
        # 分类权重
        category_weights = {
            "incident": 1.0,
            "solution": 0.9,
            "best_practice": 0.8,
            "manual": 0.7
        }
        score *= category_weights.get(knowledge_item.category, 0.5)
        
        # 时间衰减（最近的知识更相关）
        days_old = (datetime.utcnow() - knowledge_item.created_at).days
        time_decay = max(0.1, 1.0 - (days_old / 365))
        score *= time_decay
        
        return min(score, 1.0)
    
    @staticmethod
    def _calculate_content_relevance(content: str) -> float:
        """计算内容的相关性分数"""
        # 基于内容长度、结构化程度等因素
        score = 0.5
        
        # 内容长度
        if len(content) > 500:
            score += 0.1
        
        if len(content) > 1000:
            score += 0.1
        
        # 结构化程度（Markdown格式）
        if "##" in content or "###" in content:
            score += 0.1
        
        # 包含步骤列表
        if re.search(r'\d+\.', content) or re.search(r'- ', content):
            score += 0.1
        
        # 包含代码块
        if "```" in content:
            score += 0.1
        
        return min(score, 1.0)
    
    @staticmethod
    def _generate_snippet(content: str, query: str, length: int = 200) -> str:
        """生成内容摘要"""
        # 查找查询词在内容中的位置
        query_pos = content.lower().find(query.lower())
        
        if query_pos == -1:
            # 如果没找到查询词，返回开头部分
            return content[:length] + "..." if len(content) > length else content
        
        # 以查询词为中心提取摘要
        start_pos = max(0, query_pos - 50)
        end_pos = min(len(content), query_pos + length)
        
        snippet = content[start_pos:end_pos]
        
        # 确保在开头和结尾有完整句子
        if start_pos > 0:
            snippet = "..." + snippet
        if end_pos < len(content):
            snippet = snippet + "..."
        
        return snippet
    
    @staticmethod
    async def get_knowledge_statistics() -> Dict[str, Any]:
        """获取知识库统计信息"""
        db = AsyncSessionLocal()
        
        try:
            # 总数量
            total_result = await db.execute(select(func.count(KnowledgeBase.id)))
            total_count = total_result.scalar()
            
            # 分类统计
            category_result = await db.execute(
                select(KnowledgeBase.category, func.count(KnowledgeBase.id))
                .group_by(KnowledgeBase.category)
            )
            category_stats = dict(category_result.fetchall())
            
            # 标签统计
            tag_result = await db.execute(
                select(KnowledgeBase.tags)
            )
            all_tags = []
            for row in tag_result:
                if row.tags:
                    all_tags.extend([tag.strip() for tag in row.tags.split(",")])
            
            tag_stats = {}
            for tag in set(all_tags):
                tag_count = all_tags.count(tag)
                tag_stats[tag] = tag_count
            
            # 最近添加
            recent_result = await db.execute(
                select(KnowledgeBase)
                .order_by(desc(KnowledgeBase.created_at))
                .limit(5)
            )
            recent_items = recent_result.scalars().all()
            
            return {
                "total_items": total_count,
                "categories": category_stats,
                "top_tags": dict(sorted(tag_stats.items(), key=lambda x: x[1], reverse=True)[:10]),
                "recent_items": [
                    {
                        "id": item.id,
                        "title": item.title,
                        "category": item.category,
                        "created_at": item.created_at.isoformat()
                    }
                    for item in recent_items
                ],
                "generated_at": datetime.utcnow().isoformat()
            }
            
        finally:
            await db.close()
    
    @staticmethod
    async def cleanup_expired_knowledge(days: int = 365) -> int:
        """清理过期的知识条目"""
        db = AsyncSessionLocal()
        
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            
            # 删除过期的低相关性知识
            result = await db.execute(
                delete(KnowledgeBase).where(
                    and_(
                        KnowledgeBase.created_at < cutoff_date,
                        KnowledgeBase.relevance_score < 0.3
                    )
                )
            )
            
            deleted_count = result.rowcount
            await db.commit()
            
            return deleted_count
            
        finally:
            await db.close()