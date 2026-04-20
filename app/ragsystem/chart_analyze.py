import json

from app.ragsystem.data_analyze import DataAnalysisService

viz_cfg = {
        "output_dir": "charts1",
        # "output_dir": "E:/PycharmProjects/report_template/test_data",
        "save_png": True,
        "line": {"template": "plotly_dark", "width": 800, "height": 400},
        "bar": {"template": "ggplot2", "width": 600, "height": 350},
        "correlation": {"width": 700, "height": 700},
        "trend": {"template": "seaborn", "width": 900, "height": 450},
        "axis": {"tickfont": {"size": 12}, "titlefont": {"size": 14}}
    }

class analyze():
    def __init__(self):
        self.service = DataAnalysisService(viz_config=viz_cfg)
    async def get_response(self, data_source,requirements):
        if(type(data_source) == str):
            data_source = json.loads(data_source)
        result = await self.service.run_analysis(data_source, requirements)
        # 获取图表信息
        charts_info = result["visualization"]["charts"]
        return charts_info
        print(charts_info)
# data_source = {}
# requirements = {}
# async def run():
#     service = DataAnalysisService(viz_config=viz_cfg)
#     result = await service.run_analysis(data_source, requirements)
#     # 获取图表信息
#     charts_info = result["visualization"]["charts"]
#     print(charts_info)