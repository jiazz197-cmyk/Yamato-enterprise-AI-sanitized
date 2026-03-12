"""
基于位置索引的OUTPUT_RULES配置示例

这个示例展示了如何使用位置索引方式配置规则，提高代码的普适性。

优势：
1. 不依赖具体字段名称
2. 即使字段名变化，只要位置不变，配置仍然有效
3. 更容易维护和扩展

使用方法：
1. 运行 SpecificationMapping.py 查看字段位置映射
2. 根据位置索引配置规则
3. 使用 spec[index].value 或 spec@index.value 语法
"""

# 基于位置索引的配置示例
OUTPUT_RULES_POSITION_BASED = [
    {
        "name": "机架",
        "template": "机架（{parts}）",
        "parts": [
            {"source": "meta.model", "transform": ["extract_model_number", "normalize_model"]},
            # 使用位置索引 [27] 代替字段名 "25_common_bed"
            {"source": "spec[27].value", "transform": ["map_value"], "mapping": {"PAINTED ON SS": "SS", "SS": "SS"}},
            # 使用位置索引 [15] 代替字段名 "15_collating_chute"
            {"source": "spec[15].value", "transform": ["extract_degree"]}
        ]
    },
    {
        "name": "供料漏斗",
        "template": "供料漏斗（{parts}）",
        "parts": [
            {"source": "meta.model", "transform": ["extract_model_number", "normalize_model"]},
            # 使用位置索引 [2] 代替字段名 "2_surface"
            {"source": "spec[2].value", "transform": ["map_value"], "mapping": {"FLAT": "平板", "FLAT (ALL SURFACE)": "平板"}}
        ]
    },
    {
        "name": "顶锥",
        "template": "顶锥（{parts}）",
        "parts": [
            {"source": "meta.model", "transform": ["extract_model_number", "normalize_model"]},
            # 使用位置索引 [8] 代替字段名 "8_lfp_lip"
            {"source": "spec[8].value", "transform": ["get_priority_value"], "mapping": {"FLAT LIP": "平", "FLAT": "平"}}
        ]
    },
    {
        "name": "振动盘",
        "template": "振动盘（{model}{pan_type}）",
        "parts": [
            {"source": "meta.model", "key": "model", "transform": ["normalize_full_model"]},
            # 使用位置索引 [7] 代替字段名 "7_linear_feeder_pan"
            {"source": "spec[7].value", "key": "pan_type", "transform": ["map_value"], "mapping": {"SN": "SN"}}
        ]
    },
    {
        "name": "供料斗",
        "template": "供料斗（{parts}）",
        "parts": [
            {"source": "static", "value": "03系列"},
            # 使用位置索引 [11] 代替字段名 "11_fb_spring"
            {"source": "spec[11].value", "transform": ["map_value"], "mapping": {"YES": "有弹簧", "NO": "无弹簧"}},
            # 使用位置索引 [8] 代替字段名 "8_lfp_lip"
            {"source": "spec[8].value", "transform": ["get_priority_value"], "mapping": {"FLAT LIP": "平", "FLAT": "平"}}
        ]
    },
    {
        "name": "计量斗",
        "template": "计量斗（{parts}）",
        "parts": [
            {"source": "static", "value": "03系列"},
            # 使用位置索引 [14] 代替字段名 "14_wb_spring"
            {"source": "spec[14].value", "transform": ["map_value"], "mapping": {"YES": "有弹簧", "NO": "无弹簧"}},
            # 使用位置索引 [2] 代替字段名 "2_surface"
            {"source": "spec[2].value", "transform": ["map_value"], "mapping": {"FLAT": "平", "FLAT (ALL SURFACE)": "平"}}
        ]
    },
    {
        "name": "驱动单元",
        "template": "驱动单元（{parts}）",
        "parts": [
            {"source": "meta.model", "transform": ["extract_model_number", "normalize_model"]},
            {"source": "meta.model", "transform": ["extract_pattern"], "pattern": r'([A-Z])$', "conditional": {"S": "4kg"}, "default": ""},
            # 使用位置索引 [30] 代替字段名 "28_regulation"
            {"source": "spec[30].value", "transform": ["map_value"], "mapping": {"INDIA W&M": "印度W&M规格秤用", "INDIA": "印度W&M规格秤用"}}
        ]
    },
    {
        "name": "溜槽部",
        "template": "溜槽部（{parts}）",
        "parts": [
            {"source": "meta.model", "transform": ["extract_model_number", "normalize_model"]},
            # 使用位置索引 [15] 代替字段名 "15_collating_chute"
            {"source": "spec[15].value", "transform": ["extract_degree"]}
        ]
    },
    {
        "name": "收集锥",
        "template": "收集锥（{parts}）",
        "parts": [
            {"source": "meta.model", "transform": ["extract_model_number", "normalize_model"]},
            # 使用位置索引 [2] 代替字段名 "2_surface"
            {"source": "spec[2].value", "transform": ["map_value"], "mapping": {"FLAT": "平", "FLAT (ALL SURFACE)": "平"}},
            # 使用位置索引 [15] 代替字段名 "15_collating_chute"
            {"source": "spec[15].value", "transform": ["extract_degree"]}
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
            # 使用位置索引 [28] 代替字段名 "26_cable_length"
            {"source": "spec[28].value", "transform": ["map_value"], "mapping": {"8M": "标准", "8m": "标准"}}
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
            # 使用位置索引 [23] 代替字段名 "21_collection_bucket"
            {"source": "spec[23].value", "transform": ["extract_capacity"]},
            # 使用位置索引 [2] 代替字段名 "2_surface"
            {"source": "spec[2].value", "transform": ["map_value"], "mapping": {"FLAT": "平", "FLAT (ALL SURFACE)": "平"}},
            # 使用位置索引 [17] 代替字段名 "17_collating_funnel"
            {"source": "spec[17].value", "transform": ["map_value"], "mapping": {"SINGLE": "单"}}
        ]
    }
]


# 位置索引映射参考表（基于示例数据）
POSITION_INDEX_REFERENCE = """
位置索引映射参考表：
====================
[ 0] 0_power_supply_v
[ 1] 1_power_supply_hz
[ 2] 2_surface
[ 3] 3_infeed_funnel
[ 4] 4_infeed_ring
[ 5] 5_top_cone
[ 6] 6_center_vibrato
[ 7] 7_linear_feeder_pan
[ 8] 8_lfp_lip
[ 9] 9_feed_bucket
[10] 10_fb_gate
[11] 11_fb_spring
[12] 12_welgh_bucket
[13] 13_wb_gate
[14] 14_wb_spring
[15] 15_collating_chute
[16] 16_cc_baffles
[17] 17_collating_funnel
[18] degree
[19] c_c
[20] 18_cf_baffles
[21] 19_cf_l_shaped_bracket
[22] 20_product_stopper
[23] 21_collection_bucket
[24] 22_cb_gate
[25] 23_enclosure
[26] 24_detergent
[27] 25_common_bed
[28] 26_cable_length
[29] 27_software
[30] 28_regulation
[31] 29_name_plate
[32] 30_optional_spare_parts
[33] 31_display_languages
[34] 32_printer
[35] 33_operation
[36] 34_remarks

注意：实际使用时，请运行 SpecificationMapping.py 查看当前数据的位置映射
"""


if __name__ == "__main__":
    print(POSITION_INDEX_REFERENCE)
    print("\n使用示例：")
    print("from SpecificationMapping import SpecificationMapping")
    print("from config_example_position_based import OUTPUT_RULES_POSITION_BASED")
    print("")
    print("# 使用基于位置索引的配置")
    print("mapping = SpecificationMapping(json_data, output_rules=OUTPUT_RULES_POSITION_BASED)")
    print("output = mapping.generate_output_mapping()")
