from typing import Dict, Any, Optional

from pydantic import BaseModel


class MultilayerProcessingRequest(BaseModel):
    """多层处理请求"""
    source_id: int
    job_id: Optional[str] = None
    data_source: Dict[str, Any]
    processing_config: Dict[str, Any] = {
        "enable_gx_validation": True,
        "enable_presidio_detection": True,
        "enable_ai_analysis": True,
        "enable_fusion_decision": True,
        "chinese_optimization": True,
        "hardware_class": "A",
        "performance_mode": "standard"
    }
    gx_config: Optional[Dict[str, Any]] = None
    presidio_config: Optional[Dict[str, Any]] = None
    ai_config: Optional[Dict[str, Any]] = None


class MultilayerProcessingResult(BaseModel):
    """多层处理结果"""
    job_id: str
    source_id: int
    processing_layers: Dict[str, Any]
    final_assessment: Dict[str, Any]
    performance_metrics: Dict[str, Any]
    metadata_pushed: bool
