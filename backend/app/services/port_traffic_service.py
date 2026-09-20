"""端口流量历史数据服务"""
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from app.models.models import SwitchPortMetric, SwitchPort
from app.core.database import SessionLocal


class PortTrafficService:
    """端口流量历史数据管理服务"""
    
    @staticmethod
    def save_port_traffic(device_id: int, port_data: Dict[str, Any]) -> bool:
        """保存端口流量数据到历史记录"""
        try:
            db = SessionLocal()
            port_metric = SwitchPortMetric(
                device_id=device_id,
                port_index=port_data["port_index"],
                in_octets=port_data.get("in_octets", 0),
                out_octets=port_data.get("out_octets", 0),
                in_errors=port_data.get("in_errors", 0),
                out_errors=port_data.get("out_errors", 0),
                # 计算速率需要保存前一记录，这里先设为0，在调度器中计算
                in_mbps=0.0,
                out_mbps=0.0,
            )
            db.add(port_metric)
            db.commit()
            return True
        except Exception as e:
            print(f"[ERROR] 保存端口流量数据失败: {e}")
            return False
        finally:
            db.close()
    
    @staticmethod
    def get_port_traffic_history(
        device_id: int,
        port_index: int,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """获取端口流量历史数据"""
        try:
            db = SessionLocal()
            
            # 默认查询最近7天的数据
            if not end_time:
                end_time = datetime.utcnow()
            if not start_time:
                start_time = end_time - timedelta(days=7)
            
            query = db.query(SwitchPortMetric).filter(
                and_(
                    SwitchPortMetric.device_id == device_id,
                    SwitchPortMetric.port_index == port_index,
                    SwitchPortMetric.collected_at >= start_time,
                    SwitchPortMetric.collected_at <= end_time
                )
            ).order_by(SwitchPortMetric.collected_at.desc()).limit(limit)
            
            metrics = query.all()
            
            result = []
            for metric in metrics:
                result.append({
                    "id": metric.id,
                    "device_id": metric.device_id,
                    "port_index": metric.port_index,
                    "in_octets": metric.in_octets,
                    "out_octets": metric.out_octets,
                    "in_errors": metric.in_errors,
                    "out_errors": metric.out_errors,
                    "in_mbps": metric.in_mbps,
                    "out_mbps": metric.out_mbps,
                    "collected_at": metric.collected_at.isoformat() if metric.collected_at else None
                })
            
            return result
        except Exception as e:
            print(f"[ERROR] 获取端口流量历史数据失败: {e}")
            return []
        finally:
            db.close()
    
    @staticmethod
    def get_port_traffic_summary(
        device_id: int,
        port_index: int,
        hours: int = 24
    ) -> Dict[str, Any]:
        """获取端口流量统计摘要"""
        try:
            db = SessionLocal()
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(hours=hours)
            
            summary = db.query(
                func.avg(SwitchPortMetric.in_mbps).label("avg_in_mbps"),
                func.max(SwitchPortMetric.in_mbps).label("max_in_mbps"),
                func.min(SwitchPortMetric.in_mbps).label("min_in_mbps"),
                func.avg(SwitchPortMetric.out_mbps).label("avg_out_mbps"),
                func.max(SwitchPortMetric.out_mbps).label("max_out_mbps"),
                func.min(SwitchPortMetric.out_mbps).label("min_out_mbps"),
                func.sum(SwitchPortMetric.in_errors).label("total_in_errors"),
                func.sum(SwitchPortMetric.out_errors).label("total_out_errors"),
                func.count(SwitchPortMetric.id).label("data_points")
            ).filter(
                and_(
                    SwitchPortMetric.device_id == device_id,
                    SwitchPortMetric.port_index == port_index,
                    SwitchPortMetric.collected_at >= start_time,
                    SwitchPortMetric.collected_at <= end_time
                )
            ).first()
            
            if summary:
                return {
                    "avg_in_mbps": round(summary.avg_in_mbps or 0, 2),
                    "max_in_mbps": round(summary.max_in_mbps or 0, 2),
                    "min_in_mbps": round(summary.min_in_mbps or 0, 2),
                    "avg_out_mbps": round(summary.avg_out_mbps or 0, 2),
                    "max_out_mbps": round(summary.max_out_mbps or 0, 2),
                    "min_out_mbps": round(summary.min_out_mbps or 0, 2),
                    "total_in_errors": summary.total_in_errors or 0,
                    "total_out_errors": summary.total_out_errors or 0,
                    "data_points": summary.data_points or 0,
                    "period_hours": hours
                }
            return {}
        except Exception as e:
            print(f"[ERROR] 获取端口流量统计失败: {e}")
            return {}
        finally:
            db.close()
    
    @staticmethod
    def get_all_ports_with_latest_traffic(device_id: int) -> List[Dict[str, Any]]:
        """获取设备所有端口的最新流量数据"""
        try:
            db = SessionLocal()
            
            # 获取每个端口的最新流量数据
            latest_metrics = db.query(
                SwitchPortMetric.device_id,
                SwitchPortMetric.port_index,
                func.max(SwitchPortMetric.collected_at).label("latest_time")
            ).filter(
                SwitchPortMetric.device_id == device_id
            ).group_by(
                SwitchPortMetric.device_id,
                SwitchPortMetric.port_index
            ).all()
            
            result = []
            for metric in latest_metrics:
                latest_data = db.query(SwitchPortMetric).filter(
                    and_(
                        SwitchPortMetric.device_id == device_id,
                        SwitchPortMetric.port_index == metric.port_index,
                        SwitchPortMetric.collected_at == metric.latest_time
                    )
                ).first()
                
                if latest_data:
                    port_info = db.query(SwitchPort).filter(
                        and_(
                            SwitchPort.device_id == device_id,
                            SwitchPort.port_index == metric.port_index
                        )
                    ).first()
                    
                    result.append({
                        "port_index": latest_data.port_index,
                        "name": port_info.name if port_info else f"Port {latest_data.port_index}",
                        "status": port_info.status if port_info else "unknown",
                        "speed_mbps": port_info.speed_mbps if port_info else 0,
                        "in_mbps": latest_data.in_mbps,
                        "out_mbps": latest_data.out_mbps,
                        "in_octets": latest_data.in_octets,
                        "out_octets": latest_data.out_octets,
                        "in_errors": latest_data.in_errors,
                        "out_errors": latest_data.out_errors,
                        "collected_at": latest_data.collected_at.isoformat() if latest_data.collected_at else None
                    })
            
            return result
        except Exception as e:
            print(f"[ERROR] 获取端口最新流量数据失败: {e}")
            return []
        finally:
            db.close()
    
    @staticmethod
    def calculate_port_traffic_rates(device_id: int, hours: int = 24) -> bool:
        """计算端口流量速率（需要至少两个数据点）"""
        try:
            db = SessionLocal()
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(hours=hours)
            
            # 获取所有需要计算速率的端口数据
            metrics = db.query(SwitchPortMetric).filter(
                and_(
                    SwitchPortMetric.device_id == device_id,
                    SwitchPortMetric.collected_at >= start_time,
                    SwitchPortMetric.collected_at <= end_time,
                    SwitchPortMetric.in_mbps == 0.0,  # 只计算尚未计算的记录
                    SwitchPortMetric.out_mbps == 0.0
                )
            ).order_by(SwitchPortMetric.collected_at).all()
            
            # 按端口分组计算速率
            port_data = {}
            for metric in metrics:
                key = (metric.device_id, metric.port_index)
                if key not in port_data:
                    port_data[key] = []
                port_data[key].append(metric)
            
            # 计算每个端口的速率
            for (dev_id, port_idx), metric_list in port_data.items():
                if len(metric_list) < 2:
                    continue
                
                # 按时间排序
                metric_list.sort(key=lambda x: x.collected_at)
                
                # 计算相邻记录之间的速率
                for i in range(1, len(metric_list)):
                    current = metric_list[i]
                    previous = metric_list[i-1]
                    
                    if current.collected_at and previous.collected_at:
                        time_diff = (current.collected_at - previous.collected_at).total_seconds()
                        if time_diff > 0:
                            # 计算速率：字节数差值 / 时间差值 * 8 / 1000000 = Mbps
                            in_rate = (current.in_octets - previous.in_octets) * 8 / time_diff / 1000000
                            out_rate = (current.out_octets - previous.out_octets) * 8 / time_diff / 1000000
                            
                            current.in_mbps = round(in_rate, 2)
                            current.out_mbps = round(out_rate, 2)
            
            db.commit()
            return True
        except Exception as e:
            print(f"[ERROR] 计算端口流量速率失败: {e}")
            return False
        finally:
            db.close()
    
    @staticmethod
    def cleanup_old_data(days_to_keep: int = 30) -> bool:
        """清理旧的端口流量数据"""
        try:
            db = SessionLocal()
            cutoff_time = datetime.utcnow() - timedelta(days=days_to_keep)
            
            deleted_count = db.query(SwitchPortMetric).filter(
                SwitchPortMetric.collected_at < cutoff_time
            ).delete()
            
            db.commit()
            print(f"[INFO] 清理了 {deleted_count} 条旧的端口流量数据")
            return True
        except Exception as e:
            print(f"[ERROR] 清理旧端口流量数据失败: {e}")
            return False
        finally:
            db.close()