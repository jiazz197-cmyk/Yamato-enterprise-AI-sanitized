"""
规格映射模块
将提取的 JSON 格式规格数据转换为标准化的字典格式
基于配置驱动的映射系统，根据KV动态生成输出
"""
from typing import Dict, Any, Optional, List, Callable
import json
import re


# 值转换器函数库
class ValueTransformers:
    """值转换器集合，用于将原始值转换为输出格式"""
    
    @staticmethod
    def extract_model_number(value: str) -> str:
        """从完整型号中提取型号数字（如 ADW-A-0314S -> 0314S）"""
        if not value:
            return ""
        match = re.search(r'(\d{4}[A-Z]?)', value.upper())
        return match.group(1) if match else value
    
    @staticmethod
    def normalize_model(value: str) -> str:
        """标准化型号：514 -> 0314, 514A -> 0314S"""
        if not value:
            return ""
        value_upper = value.upper()
        if "514A" in value_upper:
            return value_upper.replace("514A", "0314S")
        if "514" in value_upper and "0314" not in value_upper:
            return value_upper.replace("514", "0314")
        return value_upper
    
    @staticmethod
    def normalize_full_model(value: str) -> str:
        """
        标准化完整型号（包括前缀）：ADW-A-514S -> ADW-A-0314S
        
        Args:
            value: 完整型号（如 ADW-A-514S）
        
        Returns:
            标准化后的完整型号（如 ADW-A-0314S）
        """
        if not value:
            return ""
        
        # 提取型号数字部分并标准化
        model_number = ValueTransformers.extract_model_number(value)
        if not model_number:
            return value
        
        normalized_number = ValueTransformers.normalize_model(model_number)
        
        # 替换完整型号中的数字部分
        import re
        pattern = r'(\d{4}[A-Z]?)'
        result = re.sub(pattern, normalized_number, value, count=1)
        
        return result
    
    @staticmethod
    def extract_degree(value: str) -> str:
        """从值中提取角度（如 50-degree -> 50°）"""
        if not value:
            return ""
        match = re.search(r'(\d+)[\s-]*degree', value.lower())
        if match:
            return f"{match.group(1)}°"
        if "°" in value:
            return value
        return ""
    
    @staticmethod
    def extract_capacity(value: str) -> str:
        """提取容量（如 3L, 1-way, motor -> 3L）"""
        if not value:
            return ""
        match = re.search(r'(\d+L?)', value)
        return match.group(1) if match else value
    
    @staticmethod
    def map_value(value: str, mapping: Dict[str, str]) -> str:
        """根据映射表转换值"""
        if not value:
            return ""
        value_upper = value.upper()
        return mapping.get(value_upper, value)
    
    @staticmethod
    def check_contains(value: str, keywords: List[str]) -> bool:
        """检查值是否包含关键词"""
        if not value:
            return False
        value_lower = value.lower()
        return any(keyword.lower() in value_lower for keyword in keywords)
    
    @staticmethod
    def extract_pattern(value: str, pattern: str) -> str:
        """使用正则表达式提取模式"""
        if not value:
            return ""
        match = re.search(pattern, value, re.IGNORECASE)
        return match.group(1) if match else ""
    
    @staticmethod
    def conditional_format(value: str, condition_map: Dict[str, str]) -> str:
        """根据条件映射格式化值"""
        if not value:
            return ""
        value_upper = value.upper()
        for condition, output in condition_map.items():
            if condition.upper() in value_upper:
                return output
        return value


# 输出规则配置
OUTPUT_RULES = [
    {
        "name": "机架",
        "template": "机架（{parts}）",
        "parts": [
            {"source": "meta.model", "transform": ["extract_model_number", "normalize_model"]},
            {"source": "spec.25_common_bed.value", "transform": ["map_value"], "mapping": {"PAINTED ON SS": "SS", "SS": "SS"}},
            {"source": "spec.15_collating_chute.value", "transform": ["extract_degree"]}
        ]
    },
    {
        "name": "供料漏斗",
        "template": "供料漏斗（{parts}）",
        "parts": [
            {"source": "meta.model", "transform": ["extract_model_number", "normalize_model"]},
            {"source": "spec.2_surface.value", "transform": ["map_value"], "mapping": {"FLAT": "平板", "FLAT (ALL SURFACE)": "平板"}}
        ]
    },
    {
        "name": "顶锥",
        "template": "顶锥（{parts}）",
        "parts": [
            {"source": "meta.model", "transform": ["extract_model_number", "normalize_model"]},
            {"source": "spec.8_lfp_lip.value", "transform": ["map_value"], "mapping": {"FLAT LIP": "平", "FLAT": "平"}}
        ]
    },
    {
        "name": "振动盘",
        "template": "振动盘（{model}{pan_type}）",
        "parts": [
            {"source": "meta.model", "key": "model", "transform": ["normalize_full_model"]},
            {"source": "spec.7_linear_feeder_pan.value", "key": "pan_type", "transform": ["map_value"], "mapping": {"SN": " SN"}}
        ]
    },
    {
        "name": "供料斗",
        "template": "供料斗（{parts}）",
        "parts": [
            {"source": "static", "value": "03系列"},
            {"source": "spec.11_fb_spring.value", "transform": ["map_value"], "mapping": {"YES": "有弹簧", "NO": "无弹簧"}},
            {"source": "spec.8_lfp_lip.value", "transform": ["map_value"], "mapping": {"FLAT LIP": "平", "FLAT": "平"}}
        ]
    },
    {
        "name": "计量斗",
        "template": "计量斗（{parts}）",
        "parts": [
            {"source": "static", "value": "03系列"},
            {"source": "spec.14_wb_spring.value", "transform": ["map_value"], "mapping": {"YES": "有弹簧", "NO": "无弹簧"}},
            {"source": "spec.2_surface.value", "transform": ["map_value"], "mapping": {"FLAT": "平", "FLAT (ALL SURFACE)": "平"}}
        ]
    },
    {
        "name": "驱动单元",
        "template": "驱动单元（{parts}）",
        "parts": [
            {"source": "meta.model", "transform": ["extract_model_number", "normalize_model"]},
            {"source": "meta.model", "transform": ["extract_pattern"], "pattern": r'([A-Z])$', "conditional": {"S": "4kg"}, "default": ""},
            {"source": "spec.28_regulation.value", "transform": ["map_value"], "mapping": {"INDIA W&M": "印度W&M规格秤用", "INDIA": "印度W&M规格秤用"}}
        ]
    },
    {
        "name": "溜槽部",
        "template": "溜槽部（{parts}）",
        "parts": [
            {"source": "meta.model", "transform": ["extract_model_number", "normalize_model"]},
            {"source": "spec.15_collating_chute.value", "transform": ["extract_degree"]}
        ]
    },
    {
        "name": "收集锥",
        "template": "收集锥（{parts}）",
        "parts": [
            {"source": "meta.model", "transform": ["extract_model_number", "normalize_model"]},
            {"source": "spec.2_surface.value", "transform": ["map_value"], "mapping": {"FLAT": "平", "FLAT (ALL SURFACE)": "平"}},
            {"source": "spec.15_collating_chute.value", "transform": ["extract_degree"]}
        ]
    },
    {
        "name": "标准型本体电气元件",
        "template": "标准型本体电气元件（{model}）",
        "parts": [
            {"source": "meta.model", "key": "model", "transform": ["normalize_full_model"]}
        ]
    },
    {
        "name": "配线单元",
        "template": "配线单元（{parts}）",
        "parts": [
            {"source": "meta.model", "key": "model", "transform": ["normalize_full_model"]},
            {"source": "spec.26_cable_length.value", "transform": ["map_value"], "mapping": {"8M": "标准", "8m": "标准"}}
        ]
    },
    {
        "name": "主振动器",
        "template": "主振动器（{output}）",
        "parts": [
            {"source": "meta.model", "transform": ["extract_model_number", "normalize_model"], 
             "key": "model_num"}
        ]
    },
    {
        "name": "线性振动器",
        "template": "线性振动器（{model}）",
        "parts": [
            {"source": "meta.model", "key": "model", "transform": ["normalize_full_model"]}
        ]
    },
    {
        "name": "中心柱天板密封罩",
        "template": "中心柱天板密封罩（{model_number}）",
        "parts": [
            {"source": "meta.model", "transform": ["extract_model_number", "normalize_model"], "key": "model_number"}
        ]
    },
    {
        "name": "供料锥支架",
        "template": "供料锥支架（{model}）",
        "parts": [
            {"source": "meta.model", "key": "model", "transform": ["normalize_full_model"]}
        ]
    },
    {
        "name": "包装",
        "template": "包装（{parts}）",
        "parts": [
            {"source": "meta.model", "key": "model", "transform": ["normalize_full_model"]},
            {"source": "meta.end_user_country", "transform": ["map_value"], 
             "mapping": {"CHINA": "内销"}, "default": "出口"},
            {"source": "meta.end_user_country", "transform": ["map_value"],
             "mapping": {"CHINA": "", "INDIA": "印度"}}
        ]
    },
    {
        "name": "集合斗",
        "template": "集合斗（{parts}）",
        "parts": [
            {"source": "meta.model", "transform": ["extract_model_number", "normalize_model"]},
            {"source": "spec.21_collection_bucket.value", "transform": ["extract_capacity"]},
            {"source": "spec.2_surface.value", "transform": ["map_value"], "mapping": {"FLAT": "平", "FLAT (ALL SURFACE)": "平"}},
            {"source": "spec.17_collating_funnel.value", "transform": ["map_value"], "mapping": {"SINGLE": "单"}}
        ]
    }
]


class SpecificationMapping:
    """规格映射类，用于处理产品规格数据"""
    
    def __init__(self, json_data: Dict[str, Any], output_rules: Optional[List[Dict]] = None):
        """
        初始化规格映射
        
        Args:
            json_data: 包含 meta, documents, spec 等字段的 JSON 数据
            output_rules: 输出规则配置，如果为None则使用默认规则
        """
        self.raw_data = json_data
        self.meta = json_data.get("meta", {})
        self.documents = json_data.get("documents", {})
        self.spec = json_data.get("spec", {})
        self.regulation = json_data.get("regulation", "")
        self.name_plate = json_data.get("name_plate", {})
        self.optional_spare_parts = json_data.get("optional_spare_parts", "")
        self.display_language = json_data.get("display_language", {})
        self.remarks = json_data.get("remarks", "")
        self.output_rules = output_rules or OUTPUT_RULES
        
        # 值转换器映射
        self.transformers = {
            "extract_model_number": ValueTransformers.extract_model_number,
            "normalize_model": ValueTransformers.normalize_model,
            "normalize_full_model": ValueTransformers.normalize_full_model,
            "extract_degree": ValueTransformers.extract_degree,
            "extract_capacity": ValueTransformers.extract_capacity,
            "map_value": ValueTransformers.map_value,
            "check_contains": ValueTransformers.check_contains,
            "extract_pattern": ValueTransformers.extract_pattern,
            "conditional_format": ValueTransformers.conditional_format,
        }
    
    def _get_value(self, source: str) -> Any:
        """
        根据源路径获取值
        
        Args:
            source: 源路径，格式如 "meta.model" 或 "spec.25_common_bed.value"
        
        Returns:
            对应的值
        """
        parts = source.split(".")
        value = self.raw_data
        
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            elif isinstance(value, list) and part.isdigit():
                value = value[int(part)] if int(part) < len(value) else None
            else:
                return None
            
            if value is None:
                return None
        
        return value
    
    def _apply_transforms(self, value: Any, transforms: List[str], **kwargs) -> str:
        """
        应用转换器链
        
        Args:
            value: 原始值
            transforms: 转换器名称列表
            **kwargs: 转换器参数
        
        Returns:
            转换后的值
        """
        result = str(value) if value is not None else ""
        
        for transform_name in transforms:
            if transform_name in self.transformers:
                transformer = self.transformers[transform_name]
                
                # 处理需要额外参数的转换器
                if transform_name == "map_value":
                    mapping = kwargs.get("mapping", {})
                    result = transformer(result, mapping)
                elif transform_name == "extract_pattern":
                    pattern = kwargs.get("pattern", "")
                    result = transformer(result, pattern)
                elif transform_name == "conditional_format":
                    condition_map = kwargs.get("conditional", {})
                    result = transformer(result, condition_map)
                else:
                    result = transformer(result)
        
        return result
    
    def _process_part(self, part_config: Dict[str, Any]) -> Optional[str]:
        """
        处理单个部分配置
        
        Args:
            part_config: 部分配置字典
        
        Returns:
            处理后的值字符串，如果应该跳过则返回None
        """
        source = part_config.get("source")
        
        # 静态值
        if source == "static":
            return part_config.get("value", "")
        
        # 从数据源获取值
        value = self._get_value(source)
        
        # 应用转换器
        transforms = part_config.get("transform", [])
        kwargs = {k: v for k, v in part_config.items() if k not in ["source", "transform", "key", "default", "default_key", "conditional"]}
        
        result = self._apply_transforms(value, transforms, **kwargs) if value is not None else ""
        
        # 处理条件映射（在转换后检查）
        conditional = part_config.get("conditional")
        if conditional:
            if result:
                result_upper = result.upper()
                for condition, output in conditional.items():
                    if condition.upper() in result_upper:
                        return output
            # 如果值不存在但需要条件检查，检查原始值
            if value is not None:
                value_str = str(value).upper()
                for condition, output in conditional.items():
                    if condition.upper() in value_str:
                        return output
        
        # 处理默认值
        # 如果 result 为空，或者 result 等于原始值且配置中有 mapping（说明 map_value 没找到映射），则使用 default
        use_default = False
        if not result or result == "":
            use_default = True
        elif "map_value" in transforms and value is not None:
            # 检查 map_value 是否找到了映射
            mapping = kwargs.get("mapping", {})
            if mapping and str(value).upper() not in mapping:
                # 没有找到映射，且配置了 default，使用 default
                use_default = True
        
        if use_default:
            default = part_config.get("default")
            if default:
                if "{model}" in default:
                    model = self.meta.get("model", "")
                    default = default.replace("{model}", model)
                return default
            # 如果没有默认值且值为空，返回None（跳过）
            if value is None or value == "":
                return None
        
        return result if result else None
    
    def generate_output_mapping(self) -> Dict[str, str]:
        """
        根据配置规则生成输出字符串
        
        Returns:
            包含所有组件输出字符串的字典
        """
        outputs = {}
        
        for rule in self.output_rules:
            name = rule.get("name")
            template = rule.get("template", "{parts}")
            parts_config = rule.get("parts", [])
            
            # 处理各个部分
            part_values = []
            template_vars = {}
            
            for part_config in parts_config:
                part_value = self._process_part(part_config)
                
                # 如果part有key，用于模板变量
                if "key" in part_config:
                    template_vars[part_config["key"]] = part_value or ""
                
                # 处理default_key（用于主振动器等特殊情况）
                if "default_key" in part_config and part_value:
                    template_vars[part_config["default_key"]] = part_value
                
                # 如果part_value不为None，添加到parts列表
                if part_value is not None:
                    part_values.append(part_value)
            
            # 特殊处理：主振动器的条件输出
            if name == "主振动器":
                model_num = template_vars.get("model_num", "")
                if "0314" in model_num:
                    template_vars["output"] = "YP-3NA GB01602G0458"
                else:
                    model = self.meta.get("model", "")
                    template_vars["output"] = f"({model})"
            
            # 构建输出字符串
            if "{parts}" in template:
                # 使用parts列表
                parts_str = "/".join(filter(None, part_values))
                output = template.format(parts=parts_str, **template_vars)
            else:
                # 使用模板变量
                output = template.format(**template_vars)
            
            outputs[name] = output
        
        return outputs
    
    def generate_output_list(self) -> List[str]:
        """
        生成UTF-8编码的列表格式输出（不包含remarks）
        
        Returns:
            包含所有组件输出字符串的列表（UTF-8编码）
        """
        outputs = self.generate_output_mapping()
        # 返回所有组件的输出字符串列表，按顺序排列
        return [output for output in outputs.values()]
    
    def generate_full_output(self) -> str:
        """
        生成完整的输出字符串（包含所有组件和备注）
        
        Returns:
            格式化的完整输出字符串
        """
        outputs = self.generate_output_mapping()
        
        lines = []
        lines.append("=" * 60)
        lines.append("Product Specification Output")
        lines.append("=" * 60)
        lines.append("")
        
        # 输出所有组件
        for component_name, component_output in outputs.items():
            lines.append(component_output)
        
        lines.append("")
        lines.append("-" * 60)
        lines.append("Remarks:")
        lines.append("-" * 60)
        
        # 重点关注 remarks
        if self.remarks:
            lines.append(self.remarks)
        else:
            lines.append("(No remarks)")
        
        # 如果有 spec 中的 remarks
        spec_remarks = self.get_spec_value("34_remarks")
        if spec_remarks:
            lines.append("")
            lines.append("Spec Remarks:")
            if isinstance(spec_remarks, dict):
                lines.append(spec_remarks.get("value", ""))
            else:
                lines.append(str(spec_remarks))
        
        lines.append("")
        lines.append("=" * 60)
        
        return "\n".join(lines)
    
    def get_spec_value(self, spec_key: str) -> Optional[Any]:
        """
        获取指定规格项的值
        
        Args:
            spec_key: 规格键名（支持原始键名或映射后的键名）
        
        Returns:
            规格值，如果不存在则返回 None
        """
        if spec_key in self.spec:
            value = self.spec[spec_key]
            if isinstance(value, dict):
                return value.get("value")
            return value
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        """将规格数据转换为标准字典格式"""
        return {
            "meta": self.meta,
            "documents": self.documents,
            "spec": self.spec,
            "regulation": self.regulation,
            "name_plate": self.name_plate,
            "optional_spare_parts": self.optional_spare_parts,
            "display_language": self.display_language,
            "remarks": self.remarks
        }
    
    @classmethod
    def from_json_string(cls, json_string: str, output_rules: Optional[List[Dict]] = None) -> 'SpecificationMapping':
        """从 JSON 字符串创建 SpecificationMapping 实例"""
        data = json.loads(json_string)
        return cls(data, output_rules)
    
    @classmethod
    def from_json_file(cls, file_path: str, output_rules: Optional[List[Dict]] = None) -> 'SpecificationMapping':
        """从 JSON 文件创建 SpecificationMapping 实例"""
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return cls(data, output_rules)


# 使用示例
"""
if __name__ == "__main__":
    # 示例 JSON 数据
    example_json ={
  "meta": {
    "work_no": "WG240878",
    "model": "ADW-A-0314S",
    "controller": "Yamato",
    "subsidiary_agent": "YSI",
    "end_user": "Stock",
    "end_user_country": "India",
    "destination_port": "Nhava Sheva/Mumbai",
    "ex_factory_date": "December 9, 2024"
  },
  "documents": {},
  "spec": {
    "0_power_supply_v": {
      "value": "AC230V"
    },
    "1_power_supply_hz": {
      "value": "50 Hz"
    },
    "2_surface": {
      "value": "Flat (all surface)"
    },
    "3_infeed_funnel": {
      "value": "Single"
    },
    "4_infeed_ring": {
      "value": "No"
    },
    "5_top_cone": {
      "value": "Single"
    },
    "6_center_vibrato": {
      "value": "Single"
    },
    "7_linear_feeder_pan": {
      "value": "SN"
    },
    "8_lfp_lip": {
      "value": "Flat lip",
      "note": "←Flat lip"
    },
    "9_feed_bucket": {
      "value": "Single"
    },
    "10_fb_gate": {
      "value": "↑Single door"
    },
    "11_fb_spring": {
      "value": "Yes"
    },
    "12_welgh_bucket": {
      "value": "Single"
    },
    "13_wb_gate": {
      "value": "↑Single door"
    },
    "14_wb_spring": {
      "value": "Yes"
    },
    "15_collating_chute": {
      "value": "50-degree"
    },
    "16_cc_baffles": {
      "value": "No"
    },
    "17_collating_funnel": {
      "value": "Single"
    },
    "degree": {
      "value": "50-degree"
    },
    "c_c": {
      "value": ""
    },
    "18_cf_baffles": {
      "value": "No"
    },
    "19_cf_l_shaped_bracket": {
      "value": "No",
      "note": "←Not required"
    },
    "20_product_stopper": {
      "value": "No"
    },
    "21_collection_bucket": {
      "value": "3L, 1-way, motor",
      "discharge": "Side stroke"
    },
    "22_cb_gate": {
      "value": ""
    },
    "23_enclosure": {
      "value": "No"
    },
    "24_detergent": {
      "value": "No"
    },
    "25_common_bed": {
      "value": "Painted on SS"
    },
    "26_cable_length": {
      "value": "8m"
    },
    "27_software": {
      "value": "No"
    },
    "28_regulation": {
      "value": "India W&M"
    },
    "29_name_plate": {
      "value": "SB09107H0022 (India)"
    },
    "30_optional_spare_parts": {
      "value": "No"
    },
    "31_display_languages": {
      "value": "English"
    },
    "32_printer": {
      "value": "No"
    },
    "33_operation": {
      "value": ""
    },
    "34_remarks": {
      "value": "1) Please send sealing parts required by W&M, India regulation. Sealing parts drawing is GB60202G0060 (ADW-A-0314S).2) Welgh & Actuator unit is PL5611105E001."
    }
  },
  "regulation": "",
  "name_plate": {},
  "optional_spare_parts": "",
  "display_language": {},
  "remarks": "☑ W G 240878-897, 同种\n规格做20台"
}
    
    # 创建映射实例
    mapping = SpecificationMapping(example_json)
    
    # 生成UTF-8列表格式输出（不包含remarks）
    output_list = mapping.generate_output_list()
    for item in output_list:
        print(item)        
        """