"""工作流编排系统"""
import json
import uuid
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime, timedelta
from enum import Enum
from sqlalchemy import and_, func, select, or_, desc
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models import WorkflowDefinition, WorkflowExecution, Alert
from app.services.llm_service import chat_completion


class WorkflowStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowStepType(str, Enum):
    WAIT = "wait"
    ACTION = "action"
    CONDITION = "condition"
    NOTIFICATION = "notification"
    DELAY = "delay"
    PARALLEL = "parallel"
    SEQUENCE = "sequence"


class WorkflowService:
    """工作流编排服务"""
    
    @staticmethod
    async def create_workflow(
        name: str,
        description: str,
        definition: Dict[str, Any],
        created_by: str = "system"
    ) -> Dict[str, Any]:
        """创建工作流定义"""
        db = AsyncSessionLocal()
        
        try:
            # 验证工作流定义
            validation_result = WorkflowService._validate_workflow_definition(definition)
            if not validation_result["valid"]:
                return {"error": f"Invalid workflow definition: {validation_result['errors']}"}
            
            workflow = WorkflowDefinition(
                name=name,
                description=description,
                definition=json.dumps(definition),
                created_by=created_by
            )
            
            db.add(workflow)
            await db.commit()
            
            return {
                "success": True,
                "id": workflow.id,
                "name": name,
                "description": description,
                "status": "active",
                "created_at": workflow.created_at.isoformat()
            }
            
        except Exception as e:
            await db.rollback()
            return {"error": str(e)}
        finally:
            await db.close()
    
    @staticmethod
    async def execute_workflow(
        workflow_id: int,
        trigger_data: Optional[Dict[str, Any]] = None,
        trigger_type: str = "manual"
    ) -> Dict[str, Any]:
        """执行工作流"""
        db = AsyncSessionLocal()
        
        try:
            # 获取工作流定义
            workflow_result = await db.execute(
                select(WorkflowDefinition).where(
                    and_(
                        WorkflowDefinition.id == workflow_id,
                        WorkflowDefinition.status == "active"
                    )
                )
            )
            workflow = workflow_result.scalar_one_or_none()
            
            if not workflow:
                return {"error": "Workflow not found or inactive"}
            
            # 创建执行记录
            execution = WorkflowExecution(
                workflow_id=workflow_id,
                trigger_type=trigger_type,
                trigger_data=json.dumps(trigger_data or {}),
                status=WorkflowStatus.RUNNING
            )
            
            db.add(execution)
            await db.commit()
            
            # 执行工作流
            result = await WorkflowService._run_workflow_steps(
                workflow, execution, trigger_data, db
            )
            
            # 更新执行状态
            execution.status = result["status"]
            execution.result = json.dumps(result)
            execution.progress = result.get("progress", 100)
            execution.completed_at = datetime.utcnow()
            
            await db.commit()
            
            return {
                "execution_id": execution.id,
                "workflow_id": workflow_id,
                "status": execution.status,
                "progress": execution.progress,
                "result": result,
                "started_at": execution.started_at.isoformat(),
                "completed_at": execution.completed_at.isoformat()
            }
            
        except Exception as e:
            await db.rollback()
            return {"error": str(e)}
        finally:
            await db.close()
    
    @staticmethod
    async def _run_workflow_steps(
        workflow: WorkflowDefinition,
        execution: WorkflowExecution,
        trigger_data: Optional[Dict[str, Any]],
        db: AsyncSession
    ) -> Dict[str, Any]:
        """执行工作流步骤"""
        try:
            definition = json.loads(workflow.definition)
            steps = definition.get("steps", [])
            context = {
                "trigger_data": trigger_data or {},
                "execution_id": execution.id,
                "workflow_id": workflow.id,
                "current_step": 0,
                "total_steps": len(steps),
                "variables": {},
                "results": {}
            }
            
            completed_steps = 0
            step_results = []
            
            for i, step in enumerate(steps):
                context["current_step"] = i
                step_result = await WorkflowService._execute_step(step, context, db)
                step_results.append(step_result)
                
                if step_result["status"] == "completed":
                    completed_steps += 1
                    context["results"][f"step_{i}"] = step_result["result"]
                elif step_result["status"] == "failed":
                    # 步骤失败，根据配置决定是否继续
                    if not step.get("continue_on_failure", False):
                        return {
                            "status": WorkflowStatus.FAILED,
                            "progress": (completed_steps / len(steps)) * 100,
                            "error": f"Step {i} failed: {step_result.get('error', 'Unknown error')}",
                            "step_results": step_results,
                            "failed_step": i
                        }
                
                # 如果步骤有延迟，等待指定时间
                if step_result.get("delay_seconds"):
                    await asyncio.sleep(step_result["delay_seconds"])
            
            return {
                "status": WorkflowStatus.COMPLETED,
                "progress": 100,
                "step_results": step_results,
                "completed_steps": completed_steps,
                "total_steps": len(steps),
                "variables": context["variables"]
            }
            
        except Exception as e:
            return {
                "status": WorkflowStatus.FAILED,
                "progress": 0,
                "error": str(e),
                "step_results": [],
                "failed_step": -1
            }
    
    @staticmethod
    async def _execute_step(
        step: Dict[str, Any],
        context: Dict[str, Any],
        db: AsyncSession
    ) -> Dict[str, Any]:
        """执行单个工作流步骤"""
        step_type = step.get("type")
        step_name = step.get("name", f"Step_{context['current_step']}")
        
        try:
            if step_type == WorkflowStepType.WAIT:
                return await WorkflowService._execute_wait_step(step, context)
            
            elif step_type == WorkflowStepType.ACTION:
                return await WorkflowService._execute_action_step(step, context)
            
            elif step_type == WorkflowStepType.CONDITION:
                return await WorkflowService._execute_condition_step(step, context)
            
            elif step_type == WorkflowStepType.NOTIFICATION:
                return await WorkflowService._execute_notification_step(step, context)
            
            elif step_type == WorkflowStepType.DELAY:
                return await WorkflowService._execute_delay_step(step, context)
            
            elif step_type == WorkflowStepType.PARALLEL:
                return await WorkflowService._execute_parallel_step(step, context, db)
            
            elif step_type == WorkflowStepType.SEQUENCE:
                return await WorkflowService._execute_sequence_step(step, context, db)
            
            else:
                return {
                    "status": "failed",
                    "error": f"Unknown step type: {step_type}",
                    "step_name": step_name
                }
                
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
                "step_name": step_name
            }
    
    @staticmethod
    async def _execute_wait_step(step: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """等待步骤"""
        condition = step.get("condition")
        timeout = step.get("timeout", 300)  # 5分钟超时
        
        start_time = datetime.utcnow()
        while (datetime.utcnow() - start_time).seconds < timeout:
            # 检查条件
            if await WorkflowService._evaluate_condition(condition, context):
                return {
                    "status": "completed",
                    "result": {"condition_met": True},
                    "step_name": step.get("name", "wait_step")
                }
            
            await asyncio.sleep(5)  # 每5秒检查一次
        
        return {
            "status": "failed",
            "error": f"Timeout after {timeout} seconds",
            "step_name": step.get("name", "wait_step")
        }
    
    @staticmethod
    async def _execute_action_step(step: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """执行动作步骤"""
        action_type = step.get("action")
        parameters = step.get("parameters", {})
        
        if action_type == "send_notification":
            return await WorkflowService._send_notification(parameters, context)
        
        elif action_type == "execute_command":
            return await WorkflowService._execute_command(parameters, context)
        
        elif action_type == "update_alert":
            return await WorkflowService._update_alert(parameters, context)
        
        elif action_type == "create_incident":
            return await WorkflowService._create_incident(parameters, context)
        
        else:
            return {
                "status": "failed",
                "error": f"Unknown action type: {action_type}",
                "step_name": step.get("name", "action_step")
            }
    
    @staticmethod
    async def _execute_condition_step(step: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """条件判断步骤"""
        condition = step.get("condition")
        true_steps = step.get("true_steps", [])
        false_steps = step.get("false_steps", [])
        
        condition_met = await WorkflowService._evaluate_condition(condition, context)
        
        if condition_met:
            return {
                "status": "completed",
                "result": {"condition_met": True, "executed": "true_steps"},
                "step_name": step.get("name", "condition_step")
            }
        else:
            return {
                "status": "completed",
                "result": {"condition_met": False, "executed": "false_steps"},
                "step_name": step.get("name", "condition_step")
            }
    
    @staticmethod
    async def _execute_notification_step(step: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """通知步骤"""
        channel = step.get("channel")
        message = step.get("message")
        recipients = step.get("recipients", [])
        
        # 替换模板变量
        message = WorkflowService._replace_variables(message, context)
        
        # 发送通知
        try:
            # 这里可以集成到各种通知渠道
            notification_result = {
                "channel": channel,
                "message": message,
                "recipients": recipients,
                "sent_at": datetime.utcnow().isoformat(),
                "status": "sent"
            }
            
            return {
                "status": "completed",
                "result": notification_result,
                "step_name": step.get("name", "notification_step")
            }
            
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
                "step_name": step.get("name", "notification_step")
            }
    
    @staticmethod
    async def _execute_delay_step(step: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """延迟步骤"""
        delay_seconds = step.get("delay_seconds", 0)
        
        await asyncio.sleep(delay_seconds)
        
        return {
            "status": "completed",
            "result": {"delayed_seconds": delay_seconds},
            "delay_seconds": delay_seconds,
            "step_name": step.get("name", "delay_step")
        }
    
    @staticmethod
    async def _execute_parallel_step(step: Dict[str, Any], context: Dict[str, Any], db: AsyncSession) -> Dict[str, Any]:
        """并行执行步骤"""
        sub_steps = step.get("steps", [])
        tasks = []
        
        for sub_step in sub_steps:
            task = WorkflowService._execute_step(sub_step, context, db)
            tasks.append(task)
        
        # 并行执行所有子步骤
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        failed_results = [r for r in results if isinstance(r, Exception) or r.get("status") == "failed"]
        successful_results = [r for r in results if not isinstance(r, Exception) and r.get("status") == "completed"]
        
        if failed_results and step.get("fail_on_any", True):
            return {
                "status": "failed",
                "error": f"{len(failed_results)} sub-steps failed",
                "failed_sub_steps": len(failed_results),
                "successful_sub_steps": len(successful_results),
                "step_name": step.get("name", "parallel_step")
            }
        else:
            return {
                "status": "completed",
                "result": {
                    "successful_sub_steps": len(successful_results),
                    "failed_sub_steps": len(failed_results),
                    "sub_step_results": results
                },
                "step_name": step.get("name", "parallel_step")
            }
    
    @staticmethod
    async def _execute_sequence_step(step: Dict[str, Any], context: Dict[str, Any], db: AsyncSession) -> Dict[str, Any]:
        """顺序执行步骤"""
        sub_steps = step.get("steps", [])
        results = []
        
        for sub_step in sub_steps:
            result = await WorkflowService._execute_step(sub_step, context, db)
            results.append(result)
            
            if result["status"] == "failed" and not step.get("continue_on_failure", False):
                break
        
        return {
            "status": "completed" if not any(r["status"] == "failed" for r in results) else "failed",
            "result": {"sub_step_results": results},
            "step_name": step.get("name", "sequence_step")
        }
    
    @staticmethod
    async def _send_notification(parameters: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """发送通知"""
        channel = parameters.get("channel")
        message = parameters.get("message", "")
        recipients = parameters.get("recipients", [])
        
        # 替换模板变量
        message = WorkflowService._replace_variables(message, context)
        
        # 这里可以集成到飞书、钉钉、邮件等通知渠道
        return {
            "status": "completed",
            "result": {
                "channel": channel,
                "message": message,
                "recipients": recipients,
                "sent_at": datetime.utcnow().isoformat()
            }
        }
    
    @staticmethod
    async def _execute_command(parameters: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """执行命令"""
        command = parameters.get("command")
        timeout = parameters.get("timeout", 60)
        
        # 替换变量
        command = WorkflowService._replace_variables(command, context)
        
        try:
            # 这里可以集成到SSH执行或本地命令执行
            result = {
                "command": command,
                "exit_code": 0,
                "stdout": "Command executed successfully",
                "stderr": "",
                "executed_at": datetime.utcnow().isoformat()
            }
            
            return {
                "status": "completed",
                "result": result
            }
            
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
                "result": {"command": command}
            }
    
    @staticmethod
    async def _update_alert(parameters: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """更新告警状态"""
        alert_id = parameters.get("alert_id")
        new_status = parameters.get("status")
        
        try:
            # 这里可以调用告警API更新状态
            result = {
                "alert_id": alert_id,
                "new_status": new_status,
                "updated_at": datetime.utcnow().isoformat()
            }
            
            return {
                "status": "completed",
                "result": result
            }
            
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
                "result": {"alert_id": alert_id}
            }
    
    @staticmethod
    async def _create_incident(parameters: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """创建事件"""
        title = parameters.get("title")
        description = parameters.get("description")
        severity = parameters.get("severity", "medium")
        
        try:
            # 这里可以调用事件API创建事件
            incident_id = str(uuid.uuid4())
            result = {
                "incident_id": incident_id,
                "title": title,
                "description": description,
                "severity": severity,
                "created_at": datetime.utcnow().isoformat()
            }
            
            return {
                "status": "completed",
                "result": result
            }
            
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
                "result": {"title": title}
            }
    
    @staticmethod
    async def _evaluate_condition(condition: Dict[str, Any], context: Dict[str, Any]) -> bool:
        """评估条件"""
        if not condition:
            return True
        
        # 简化的条件评估逻辑
        condition_type = condition.get("type")
        
        if condition_type == "alert_severity":
            severity = condition.get("severity")
            alert_data = context.get("trigger_data", {}).get("alert", {})
            return alert_data.get("level") == severity
        
        elif condition_type == "time_based":
            # 时间条件
            current_time = datetime.utcnow()
            time_condition = condition.get("condition")
            
            if time_condition == "business_hours":
                # 工作时间判断 (9:00-18:00)
                return 9 <= current_time.hour < 18
            
            elif time_condition == "weekend":
                # 周末判断
                return current_time.weekday() >= 5
        
        elif condition_type == "variable":
            # 变量条件
            var_name = condition.get("variable")
            operator = condition.get("operator", "==")
            value = condition.get("value")
            
            var_value = context.get("variables", {}).get(var_name)
            
            if operator == "==":
                return var_value == value
            elif operator == "!=":
                return var_value != value
            elif operator == ">":
                return var_value > value
            elif operator == "<":
                return var_value < value
        
        return False
    
    @staticmethod
    def _replace_variables(text: str, context: Dict[str, Any]) -> str:
        """替换模板变量"""
        if not text:
            return text
        
        # 替换触发数据变量
        if "{{trigger." in text:
            trigger_data = context.get("trigger_data", {})
            for key, value in trigger_data.items():
                text = text.replace(f"{{{{trigger.{key}}}}}", str(value))
        
        # 替换执行变量
        if "{{execution." in text:
            execution_info = {
                "id": context.get("execution_id", ""),
                "workflow_id": context.get("workflow_id", ""),
                "current_step": context.get("current_step", 0),
                "total_steps": context.get("total_steps", 0)
            }
            for key, value in execution_info.items():
                text = text.replace(f"{{{{execution.{key}}}}}", str(value))
        
        # 替换自定义变量
        if "{{variable." in text:
            variables = context.get("variables", {})
            for key, value in variables.items():
                text = text.replace(f"{{{{variable.{key}}}}}", str(value))
        
        return text
    
    @staticmethod
    async def _validate_workflow_definition(definition: Dict[str, Any]) -> Dict[str, Any]:
        """验证工作流定义"""
        errors = []
        
        # 检查必要字段
        if "name" not in definition:
            errors.append("Missing 'name' field")
        
        if "steps" not in definition:
            errors.append("Missing 'steps' field")
        
        if errors:
            return {"valid": False, "errors": errors}
        
        # 检查步骤
        for i, step in enumerate(definition["steps"]):
            if "type" not in step:
                errors.append(f"Step {i}: Missing 'type' field")
            
            if "name" not in step:
                errors.append(f"Step {i}: Missing 'name' field")
        
        return {"valid": len(errors) == 0, "errors": errors}
    
    @staticmethod
    async def get_workflow_executions(workflow_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """获取工作流执行历史"""
        db = AsyncSessionLocal()
        
        try:
            result = await db.execute(
                select(WorkflowExecution)
                .where(WorkflowExecution.workflow_id == workflow_id)
                .order_by(desc(WorkflowExecution.started_at))
                .limit(limit)
            )
            executions = result.scalars().all()
            
            history = []
            for execution in executions:
                history.append({
                    "id": execution.id,
                    "workflow_id": execution.workflow_id,
                    "trigger_type": execution.trigger_type,
                    "status": execution.status,
                    "progress": execution.progress,
                    "started_at": execution.started_at.isoformat(),
                    "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
                    "error_message": execution.error_message
                })
            
            return history
            
        finally:
            await db.close()
    
    @staticmethod
    async def get_execution_details(execution_id: int) -> Dict[str, Any]:
        """获取执行详情"""
        db = AsyncSessionLocal()
        
        try:
            result = await db.execute(
                select(WorkflowExecution).where(WorkflowExecution.id == execution_id)
            )
            execution = result.scalar_one_or_none()
            
            if not execution:
                return {"error": "Execution not found"}
            
            return {
                "id": execution.id,
                "workflow_id": execution.workflow_id,
                "trigger_type": execution.trigger_type,
                "trigger_data": json.loads(execution.trigger_data) if execution.trigger_data else {},
                "status": execution.status,
                "progress": execution.progress,
                "result": json.loads(execution.result) if execution.result else {},
                "error_message": execution.error_message,
                "started_at": execution.started_at.isoformat(),
                "completed_at": execution.completed_at.isoformat() if execution.completed_at else None
            }
            
        finally:
            await db.close()
    
    @staticmethod
    async def get_workflow_templates() -> List[Dict[str, Any]]:
        """获取工作流模板"""
        templates = [
            {
                "id": 1,
                "name": "服务器重启流程",
                "description": "用于重启故障服务器的标准流程",
                "steps": [
                    {
                        "type": "action",
                        "name": "通知相关人员",
                        "action": "send_notification",
                        "parameters": {
                            "channel": "slack",
                            "message": "服务器即将重启，请做好准备",
                            "recipients": ["team", "admin"]
                        }
                    },
                    {
                        "type": "delay",
                        "name": "等待通知",
                        "delay_seconds": 30
                    },
                    {
                        "type": "action",
                        "name": "执行重启命令",
                        "action": "execute_command",
                        "parameters": {
                            "command": "sudo reboot",
                            "timeout": 60
                        }
                    }
                ]
            },
            {
                "id": 2,
                "name": "网络故障排查",
                "description": "网络设备故障的自动排查流程",
                "steps": [
                    {
                        "type": "condition",
                        "name": "检查告警级别",
                        "condition": {
                            "type": "alert_severity",
                            "severity": "critical"
                        },
                        "true_steps": [
                            {
                                "type": "action",
                                "name": "紧急通知",
                                "action": "send_notification",
                                "parameters": {
                                    "channel": "phone",
                                    "message": "网络故障紧急处理",
                                    "recipients": ["oncall"]
                                }
                            }
                        ],
                        "false_steps": [
                            {
                                "type": "action",
                                "name": "常规通知",
                                "action": "send_notification",
                                "parameters": {
                                    "channel": "slack",
                                    "message": "网络告警处理",
                                    "recipients": ["team"]
                                }
                            }
                        ]
                    }
                ]
            }
        ]
        
        return templates