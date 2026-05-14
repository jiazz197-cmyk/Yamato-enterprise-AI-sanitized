"""
智能组合秤订单填表 Schema
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.core.config import settings


class ClosingFormSubmit(BaseModel):
    """填表提交数据"""

    date: Optional[str] = Field(None, description="日期，格式：YYYY-MM-DD HH:mm:ss")
    closing_date: Optional[str] = Field(None, description="成交时间，格式：YYYY-MM-DD")
    customer_name: str = Field(..., description="客户名称")
    product_type: str = Field(..., description="产品类型")
    model_spec: str = Field(..., description="型号规格")
    quantity: int = Field(..., ge=1, description="数量")
    price_excluding_tax: float = Field(..., ge=0, description="原价不含税")
    production_number: str = Field(..., description="生产制造编号")
    material_name: str = Field(..., description="物料名称")
    weighing_spec: str = Field(..., description="称重规格")
    speed: int = Field(..., ge=0, description="速度")
    precision: str = Field(..., description="精度")
    top_cone_type: str = Field(..., description="顶锥形式")
    linear_vibration_type: str = Field(..., description="线振形式")
    material_layer_ring: str = Field(..., description="料层调整圈")
    feed_hopper: str = Field(..., description="供料斗")
    metering_hopper: str = Field(..., description="计量斗")
    memory_hopper: str = Field(..., description="记忆斗")
    chute_angle: str = Field(..., description="溜槽角度")
    collection_hopper_type: str = Field(..., description="集合斗形式")
    scale_type: str = Field(..., description="单双秤/混料/外挂/特殊")
    image_url_1: Optional[str] = Field(None, max_length=512)
    image_url_2: Optional[str] = Field(None, max_length=512)

    @field_validator("image_url_1", "image_url_2")
    @classmethod
    def validate_image_url_format(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.startswith(f"{settings.CLOSING_FORM_IMAGE_PREFIX}/"):
            raise ValueError("非法的图片路径")
        return v

    def to_formatted_text(self) -> str:
        """生成符合要求的格式字符串"""
        date_str = self.date or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        parts = [
            f"日期：{date_str}",
            f"成交时间：{self.closing_date or ''}",
            f"客户名称：{self.customer_name}",
            f"产品类型：{self.product_type}",
            f"型号规格：{self.model_spec}",
            f"数量：{self.quantity}",
            f"原价不含税：{self.price_excluding_tax}",
            f"生产制造编号：{self.production_number}",
            f"物料名称：{self.material_name}",
            f"称重规格：{self.weighing_spec}",
            f"速度：{self.speed}",
            f"精度：{self.precision}",
            f"顶锥形式：{self.top_cone_type}",
            f"线振形式：{self.linear_vibration_type}",
            f"料层调整圈：{self.material_layer_ring}",
            f"供料斗：{self.feed_hopper}",
            f"计量斗：{self.metering_hopper}",
            f"记忆斗：{self.memory_hopper}",
            f"溜槽角度：{self.chute_angle}",
            f"集合斗形式：{self.collection_hopper_type}",
            f"单双秤/混料/外挂/特殊：{self.scale_type}",
        ]
        if self.image_url_1:
            parts.append(f"图片url：{self.image_url_1}")
        if self.image_url_2:
            parts.append(f"图片url：{self.image_url_2}")
        return ", ".join(parts)


class ClosingFormSubmitResponse(BaseModel):
    """填表提交响应"""

    success: bool = True
    message: str = "提交成功"
    form_text: Optional[str] = None
    image_url_1: Optional[str] = None
    image_url_2: Optional[str] = None


class ClosingFormRecord(BaseModel):
    """单条已提交表单记录"""

    id: str
    text: str
    upload_time: Optional[str] = None
    uploader: str = ""
    status: str = "pending"
    image_url_1: Optional[str] = None
    image_url_2: Optional[str] = None


class ClosingFormRejectResponse(BaseModel):
    """拒绝审批响应"""

    success: bool = True
    message: str = "审批不通过"


class ClosingFormListResponse(BaseModel):
    """用户已提交表单列表响应"""

    success: bool = True
    total: int = 0
    records: list[ClosingFormRecord] = []


class ClosingFormApproveResponse(BaseModel):
    """审批响应"""

    success: bool = True
    message: str = "审批通过"


class ClosingFormDeleteResponse(BaseModel):
    """删除响应"""

    success: bool = True
    message: str = "删除成功"
    deleted_id: str


class ImageUploadResponse(BaseModel):
    """图片上传响应"""

    success: bool = True
    object_name: str


class Collection2Record(BaseModel):
    """data_doc_collection_2 单条记录"""

    id: str
    text: str
    file_name: Optional[str] = None
    upload_time: Optional[str] = None
    uploader: str = ""
    status: str = "approved"


class Collection2ListResponse(BaseModel):
    """data_doc_collection_2 列表响应"""

    success: bool = True
    total: int = 0
    records: list[Collection2Record] = []
