"""
关键词归一化模块。

负责将结构化 keywords 请求体转换为可执行查询关键词组。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence


YES_VALUES = {"yes", "true", "y", "1", "是"}
NO_VALUES = {"no", "false", "n", "0", "否", "无"}

SEMANTIC_FIELD_TOKENS: Dict[str, str] = {
    "detergent": "detergent",
    "fbspring": "fb spring",
    "fb弹簧": "fb spring",
    "wbspring": "wb spring",
    "wb弹簧": "wb spring",
    "ccbaffles": "cc baffles",
    "cc挡板": "cc baffles",
    "挡板": "cc baffles",
    "cfbaffles": "cf baffles",
    "cf挡板": "cf baffles",
    "memoryspring": "memory spring",
    "记忆弹簧": "memory spring",
}

LFP_LIP_KEYS = {"lfplip", "lfp唇口", "lfp唇"}
CF_L_BRACKET_KEYS = {"cflshapedbracket", "cfl型支架", "l型支架"}


def _normalize_key_name(key_text: str) -> str:
    return re.sub(r"[\s_\-]", "", key_text.lower())


def _to_tristate(value: Any) -> str:
    """将输入值归一化为 yes/no/other 三态。"""
    if isinstance(value, bool):
        return "yes" if value else "no"

    text = str(value).strip().lower()
    if text in YES_VALUES:
        return "yes"
    if text in NO_VALUES:
        return "no"
    return "other"


def normalize_pdm_keywords(value: Any) -> List[List[str]]:
    """
    将 keywords 统一转换为多组原始关键词。

    仅支持以下输入格式:
    1) {"type": "机架", "attr": {"surface": "flat", "detergent": True}}
    2) [{"type": "机架", "attr": {"surface": "flat", "detergent": True}}]
    3) [{"type": "机架", "attr": {"surface": "flat", "detergent": True}}, {"type": "供料斗", "attr": {"LFP唇口": "No"}}]
    """

    def normalize_structured_item(item: Dict[str, Any]) -> List[str]:
        def append_value_with_key_semantics(container: List[str], key_text: str, value: Any) -> None:
            if value is None:
                return

            normalized_key = _normalize_key_name(key_text)
            semantic_token = SEMANTIC_FIELD_TOKENS.get(normalized_key)
            is_lfp_lip = normalized_key in LFP_LIP_KEYS
            is_cf_l_bracket = normalized_key in CF_L_BRACKET_KEYS
            is_c_c = normalized_key in {"cc", "c-c", "c到c"}
            is_collection_bucket = normalized_key in {"collectionbucket", "集合斗参数", "集合斗"}
            is_collating_funnel = normalized_key in {"collatingfunnel", "供料漏斗", "供料锥"}
            is_center_vibrator_key = normalized_key in {"centervibrator", "中心振动器"}
            is_end_user_country = normalized_key in {"endusercountry", "country", "终端国家"}
            is_vibrating = "振动盘" in type_name
            is_feeding_hopper = "供料斗" in type_name
            is_weigh_bucket = "计量斗" in type_name
            is_collecting_cone = "收集锥" in type_name or "集料漏斗" in type_name
            is_packaging = "包装" in type_name

            if is_c_c:
                text_value = str(value).strip()
                if not text_value:
                    return
                lower_text_value = text_value.lower()
                if lower_text_value in NO_VALUES:
                    return
                # C-C 有值时，优先生成 C-C=数值，同时兼容 C-C+数值 的写法。
                container.append(f"C-C={text_value}")
                container.append(f"C-C{text_value}")
                container.append(f"中心距{text_value}")
                return

            if is_collection_bucket:
                text_value = str(value).strip().lower()
                if not text_value:
                    return
                before_count = len(container)
                if "3l" in text_value:
                    container.append("3L")
                if "1-way" in text_value or "1 way" in text_value:
                    container.append("1-way")
                if "2-way" in text_value or "2 way" in text_value:
                    container.append("2-way")
                if "motor" in text_value:
                    container.append("motor")
                if "pneumatic" in text_value:
                    container.append("pneumatic")
                if "side stroke" in text_value:
                    container.append("side stroke")
                if "center" in text_value and "drive" in text_value and "double" in text_value:
                    container.append("center double drive")
                elif "center" in text_value and "drive" in text_value:
                    container.append("center drive")
                if "单横" in text_value:
                    container.append("单横")
                if "双横" in text_value:
                    container.append("双横")
                if len(container) > before_count:
                    return

            value_state = _to_tristate(value)
            if value_state in {"yes", "no"}:
                if value_state == "yes":
                    if semantic_token:
                        container.append(semantic_token)
                    elif key_text:
                        container.append(key_text)
                else:
                    if semantic_token:
                        container.append(f"{semantic_token}:no")
                    elif is_cf_l_bracket and is_collecting_cone:
                        # 收集锥规则: No 对应无L型支架，不作为参数加入。
                        return
                    elif is_lfp_lip:
                        if is_vibrating:
                            container.append("无")
                        # 供料斗和计量斗的 LFP lip = No 不加入关键词。
                        elif is_feeding_hopper or is_weigh_bucket:
                            return
                return

            text = str(value).strip()
            if not text:
                return

            if is_end_user_country and is_packaging:
                lower_country = text.lower()
                if lower_country in {"india", "indian", "印度"}:
                    container.append("india")
                    container.append("!非印度")
                    return
                if lower_country in {"china", "chinese", "中国", "国内"}:
                    container.append("china")
                    return
                # 非印度国家: 主检国外类关键词，同时排除印度/国内语义干扰。
                container.append("non-india")
                container.append("!印")
                container.append("!国内")
                container.append("!非印度")
                return

            lower_text = text.lower()

            # 针对枚举值的通用归一化。
            if is_center_vibrator_key or is_collating_funnel:
                if lower_text in {"single"}:
                    container.append("single")
                    return
                if lower_text in {"double", "twin", "divided two", "dividedtwo", "divided-two"}:
                    container.append("double" if is_center_vibrator_key else "twin")
                    return

            container.append(text)

        group: List[str] = []

        type_name = str(item.get("type") or "").strip()
        if type_name:
            group.append(type_name)

        attr = item.get("attr")

        if isinstance(attr, dict):
            for key, raw_value in attr.items():
                key_text = str(key).strip()

                if isinstance(raw_value, Sequence) and not isinstance(raw_value, (str, bytes, bytearray, dict)):
                    for sub_value in raw_value:
                        append_value_with_key_semantics(group, key_text, sub_value)
                    continue

                append_value_with_key_semantics(group, key_text, raw_value)

        # 去重并保持顺序
        return list(dict.fromkeys(group))

    # 单个结构化对象：{"type": "机架", "attr": {...}}
    if isinstance(value, dict):
        value = [value]

    if not isinstance(value, list) or not value:
        return []

    # 仅接受结构化形式: [{"type": "机架", "attr": {...}}, ...]
    if not all(isinstance(item, dict) for item in value):
        return []

    groups: List[List[str]] = []
    for item in value:
        group = normalize_structured_item(item)
        if group:
            groups.append(group)
    return groups
