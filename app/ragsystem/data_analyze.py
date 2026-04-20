import ast
import asyncio
import json
import os
from datetime import datetime
from enum import Enum
from typing import List, Dict, Any, Union, Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import polars as pl
from polars import Utf8
from polars.selectors import numeric
from pydantic import BaseModel


# --- 分析任务枚举 ---
class AnalysisTask(Enum):
    CLEAN = "clean"
    ANALYZE = "analyze"
    VISUALIZE = "visualize"

# --- 数据上下文 ---
class DataContext(BaseModel):
    data_source: Union[str, Dict[str, Any]]
    requirements: Dict[str, Any]
    history: List[Dict[str, Any]] = []

# --- 数据清洗工具 ---
class DataCleaner:
    async def clean_data(self, data: pl.DataFrame) -> Dict[str, Any]:
        profile = await asyncio.to_thread(self._profile_data, data)
        issues = await asyncio.to_thread(self._identify_issues, data, profile)
        cleaned_data = await asyncio.to_thread(self._perform_cleaning, data, issues)
        return {
            "cleaned_data": {"header": cleaned_data.columns, "rows": cleaned_data.to_dicts()},
            "profile": profile,
            "issues": issues
        }

    def _profile_data(self, data: pl.DataFrame) -> Dict[str, Any]:
        return {"columns": data.columns, "rows": data.height}

    def _check_missing_values(self, data: pl.DataFrame) -> List[Dict[str, Any]]:
        issues, null_counts = [], data.null_count()
        for col in data.columns:
            count = null_counts.select(col).item()
            if count > 0:
                issues.append({"column": col, "type": "missing", "count": count})
        return issues

    def _detect_outliers(self, data: pl.DataFrame) -> List[Dict[str, Any]]:
        return []

    def _check_data_types(self, data: pl.DataFrame) -> List[Dict[str, Any]]:
        return []

    def _identify_issues(self, data: pl.DataFrame, profile: Dict[str, Any]) -> List[Dict[str, Any]]:
        return self._check_missing_values(data) + self._detect_outliers(data) + self._check_data_types(data)

    def _handle_missing(self, data: pl.DataFrame, issue: Dict[str, Any]) -> pl.DataFrame:
        col = issue["column"]
        if data[col].dtype in (pl.Float64, pl.Int64):
            return data.with_columns(pl.col(col).fill_null(data[col].mean()))
        return data.with_columns(pl.col(col).fill_null("missing"))

    def _handle_outlier(self, data: pl.DataFrame, issue: Dict[str, Any]) -> pl.DataFrame:
        return data

    def _handle_type(self, data: pl.DataFrame, issue: Dict[str, Any]) -> pl.DataFrame:
        return data

    def _perform_cleaning(self, data: pl.DataFrame, issues: List[Dict[str, Any]]) -> pl.DataFrame:
        cleaned = data.clone()
        for issue in issues:
            if issue["type"] == "missing": cleaned = self._handle_missing(cleaned, issue)
            elif issue["type"] == "outlier": cleaned = self._handle_outlier(cleaned, issue)
            elif issue["type"] == "type": cleaned = self._handle_type(cleaned, issue)
        return cleaned

# --- 数据分析工具 ---
class DataAnalyzer:
    async def analyze_features(self, data: pl.DataFrame, requirements: Dict[str, Any]) -> Dict[str, Any]:
        stats = await asyncio.to_thread(lambda: data.describe().to_dicts())
        corrs = await asyncio.to_thread(self._correlations, data)
        return {"statistics": stats, "correlations": corrs, "trends": {}}

    def _correlations(self, data: pl.DataFrame) -> List[Dict[str, Any]]:
        try:
            return data.select(numeric()).corr().to_dicts()
        except:
            return []

# --- 数据可视化工具 ---
class DataVisualizer:
    def __init__(self, viz_config: Dict[str, Any] = None):
        self.viz_config = viz_config or {}
        # ① 从配置里读入 y 轴列过滤关键字（子串）
        self.y_pattern = self.viz_config.get("y_pattern", None)
        self.output_dir = self.viz_config.get("output_dir", "charts")
        self.save_png = self.viz_config.get("save_png", False)
        os.makedirs(self.output_dir, exist_ok=True)

    def _apply_format(self, fig: go.Figure, chart_type: str) -> go.Figure:
        fmt = self.viz_config.get(chart_type, {})
        if fmt:
            fig.update_layout(**{k: v for k, v in fmt.items()
                                  if k in ("template", "width", "height", "title_font")})
            axis = self.viz_config.get("axis", {})
            if axis:
                fig.update_xaxes(**axis)
                fig.update_yaxes(**axis)
        return fig

    def _ts(self) -> str:
        return datetime.now().strftime("%Y%m%d%H%M%S")

    def _save_html_and_png(self, fig: go.Figure, prefix: str) -> Tuple[str, Union[str, None]]:
        ts = self._ts()
        html_name = f"{prefix}_{ts}.html"
        html_path = os.path.join(self.output_dir, html_name)
        # 1) 先把完整 HTML 写出来
        pio.write_html(fig, file=html_path, auto_open=False, full_html=True)
        # 2) 读取刚写的文件，给 <body> 加上居中样式
        with open(html_path, 'r', encoding='utf-8') as f:
            html = f.read()
        # 这里加水平居中 text-align，也可加垂直居中 align-items（需 display:flex）
        html = html.replace(
            '<body>',
            # '<body style="display:flex; justify-content:center; align-items:center; margin:0; height:100vh;">'
            '<body style="text-align:center; margin:0;">'
        )
        # 3) 覆写回去
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html)
        # 4) PNG 生成不变
        png_name = None
        if self.save_png:
            png_name = f"{prefix}_{ts}.png"
            png_path = os.path.join(self.output_dir, png_name)
            fig.write_image(png_path, scale=3)  # scale=3 放大3倍,控制清晰度

        # 转为绝对路径后再返回
        html_name = os.path.abspath(html_path)
        png_name = os.path.abspath(png_path) if png_path else None
        # return os.path.splitext(html_name)[0], (os.path.splitext(png_name)[0] if png_name else None) # 去除扩展名
        return html_name, png_name  # 不删除扩展名

    def _select_x(self, df: pl.DataFrame) -> Union[str, None]:
        # 所有字符串列，且值不全相同
        str_cols = [c for c, dt in df.schema.items() if dt == Utf8]
        variable = [
            c for c in str_cols
            if df.select(pl.col(c).n_unique()).item() > 1
        ]
        return variable[0] if variable else None

    def _select_y_cols(self, df: pl.DataFrame) -> List[str]:
        # 返回所有数值列
        return df.select(pl.col(pl.Float64, pl.Int64)).columns

    # 联合折线图
    def _plot_combined_line_charts(self, data: pl.DataFrame) -> List[Dict[str, Any]]:
        x_col = self._select_x(data)
        y_cols = self._select_y_cols(data)

        if self.y_pattern:
            y_cols = [c for c in y_cols if self.y_pattern in c]

        results: List[Dict[str, Any]] = []
        if not x_col or len(y_cols) < 2:
            return results

        pdf = data.to_pandas()
        fig = go.Figure()

        # 为每一列添加折线图
        for y in y_cols:
            fig.add_trace(go.Scatter(x=pdf[x_col], y=pdf[y], mode='lines', name=y))

        fig.update_layout(
                          xaxis_title=x_col,
                          yaxis_title="Values",
                          font=dict(family="Microsoft YaHei", size=14)
                          )
        name_html, name_png = self._save_html_and_png(fig, "combined_line")
        # results.append({
        #     "name": name_html,
        #     "png": name_png,
        #     "type": "combined_line",
        #     "title": f"联合折线图"
        # })
        results.append({
            "html_path": name_html,
            "pdf_word_path": name_png
        })
        return results

    # 联合柱状图
    def _plot_combined_bar_charts(self, data: pl.DataFrame) -> List[Dict[str, Any]]:
        x_col = self._select_x(data)
        y_cols = self._select_y_cols(data)

        if self.y_pattern:
            y_cols = [c for c in y_cols if self.y_pattern in c]

        results: List[Dict[str, Any]] = []
        if not x_col or len(y_cols) < 2:
            return results

        pdf = data.to_pandas()
        fig = go.Figure()

        # 为每一列添加柱状图
        for y in y_cols:
            fig.add_trace(go.Bar(x=pdf[x_col], y=pdf[y], name=y))

        fig.update_layout(
                          xaxis_title=x_col,
                          yaxis_title="Values",
                          font=dict(family="Microsoft YaHei", size=14)
                          )
        name_html, name_png = self._save_html_and_png(fig, "combined_bar")
        # results.append({
        #     "name": name_html,
        #     "png": name_png,
        #     "type": "combined_bar",
        #     "title": f"联合柱状图"
        # })
        results.append({
            "html_path": name_html,
            "pdf_word_path": name_png
        })
        return results

    # 画折线图
    def _plot_line_charts(self, data: pl.DataFrame) -> List[Dict[str, Any]]:
        x_col = self._select_x(data)
        y_cols = self._select_y_cols(data)

        if self.y_pattern:
            y_cols = [c for c in y_cols if self.y_pattern in c]

        results: List[Dict[str, Any]] = []
        if not x_col or len(y_cols) < 1:
            return results

        pdf = data.to_pandas()
        fig = go.Figure()

        # 为每一列添加折线图
        for y in y_cols:
            fig.add_trace(go.Scatter(x=pdf[x_col], y=pdf[y], mode='lines', name=y))

        fig.update_layout(
                          xaxis_title=x_col,
                          yaxis_title="Values",
                          font=dict(family="Microsoft YaHei", size=14)
                          )
        name_html, name_png = self._save_html_and_png(fig, "line_chart")
        # results.append({
        #     "name": name_html,
        #     "png": name_png,
        #     "type": "line",
        #     "title": f"折线图"
        # })
        results.append({
            "html_path": name_html,
            "pdf_word_path": name_png
        })
        return results

    # 画柱状图
    def _plot_bar_charts(self, data: pl.DataFrame) -> List[Dict[str, Any]]:
        x_col = self._select_x(data)
        y_cols = self._select_y_cols(data)

        if self.y_pattern:
            y_cols = [c for c in y_cols if self.y_pattern in c]

        results: List[Dict[str, Any]] = []
        if not x_col or len(y_cols) < 1:
            return results

        pdf = data.to_pandas()
        fig = go.Figure()

        # 为每一列添加柱状图
        for y in y_cols:
            fig.add_trace(go.Bar(x=pdf[x_col], y=pdf[y], name=y))

        fig.update_layout(
                          xaxis_title=x_col,
                          yaxis_title="Values",
                          font=dict(family="Microsoft YaHei", size=14)
                          )
        name_html, name_png = self._save_html_and_png(fig, "bar_chart")
        # results.append({
        #     "name": name_html,
        #     "png": name_png,
        #     "type": "bar",
        #     "title": f"柱状图"
        # })
        results.append({
            "html_path": name_html,
            "pdf_word_path": name_png
        })
        return results

    # 画统计表
    def _plot_stats_table(self, stats: List[Dict[str, Any]]) -> Tuple[Union[str, None], Union[str, None]]:
        if not stats:
            return None, None
        df = pd.DataFrame(stats)

        # 1) 计算每列宽度，这里示例每列 120px
        col_widths = [120] * len(df.columns)

        # 2) 生成 format 列表：数值列保留两位小数，非数值列不格式化
        formats = []
        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]):
                formats.append(".2f")
            else:
                formats.append("")  # 字符串列使用默认

        fig = go.Figure(data=[go.Table(
            columnwidth=col_widths,
            header=dict(
                values=list(df.columns),
                font=dict(family="Microsoft YaHei", size=14),
                align="center"
            ),
            cells=dict(
                values=[df[col].tolist() for col in df.columns],
                font=dict(family="Microsoft YaHei", size=12),
                align="center",
                format=formats
            )
        )])

        # 3) 设置整体画布宽度，留点余量
        total_width = sum(col_widths) + 50
        fig.update_layout(

            width=total_width,
            height=400
        )

        # 4) 应用用户自定义样式
        fig = self._apply_format(fig, 'statistics')

        return self._save_html_and_png(fig, 'statistics')

    # 画相关性热力图
    def _plot_corr_heatmap(self, corr_data: List[List[float]]) -> Tuple[str, Union[str, None]]:
        if not corr_data or not corr_data[0]:
            return None, None

        # 1) 构造 DataFrame 并获取标签
        corr_df = pd.DataFrame(corr_data)
        cols = corr_df.columns.astype(str).tolist()

        # 2) 创建 heatmap，带上 text 和 texttemplate
        fig = go.Figure(data=go.Heatmap(
            z=corr_df.values,
            x=cols,
            y=cols,
            # colorscale='Viridis',
            # 这里改成单色渐变 Blues
            colorscale='Blues',
            colorbar=dict(title="Correlation"),
            text=np.round(corr_df.values, 2),  # 格子里显示的数字（保留两位小数）
            texttemplate="%{text}",  # 告诉 Plotly 把 text 渲染出来
            hoverinfo="z"  # hover 显示原始 z 值
        ))

        # 3) 标题和格式化（如果有的话）
        fig.update_layout(title="相关性热力图")

        # 4) 保存并返回文件名
        name_html, name_png = self._save_html_and_png(fig, "corr_heatmap")
        return name_html, name_png

    # 画趋势图
    def _plot_trend(self, trend_key: str, trend_data: List[Dict[str, Any]]) -> Tuple[str, Union[str, None]]:
        if not trend_data:
            return None, None

        trend_df = pd.DataFrame(trend_data)
        fig = go.Figure(data=[go.Scatter(x=trend_df["date"], y=trend_df["value"], mode='lines', name=trend_key)])

        fig.update_layout(
                          xaxis_title="Date",
                          yaxis_title="Value",
                          font=dict(family="Microsoft YaHei", size=14)
                          )
        name_html, name_png = self._save_html_and_png(fig, f"trend_{trend_key}")
        return name_html, name_png

    async def create_visualizations(
        self,
        data: pl.DataFrame,
        analysis: Dict[str, Any],
        chart_type: str = None
    ) -> Dict[str, Any]:
        charts: List[Dict[str, Any]] = []

        # 指定类型：只生成该类型所有图
        if chart_type == "line":
            charts.extend(await asyncio.to_thread(self._plot_line_charts, data))
            return {"charts": charts, "layout": "filtered"}

        if chart_type == "bar":
            charts.extend(await asyncio.to_thread(self._plot_bar_charts, data))
            return {"charts": charts, "layout": "filtered"}

        if chart_type == "combined_line":
            charts.extend(await asyncio.to_thread(self._plot_combined_line_charts, data))
            return {"charts": charts, "layout": "filtered"}

        if chart_type == "combined_bar":
            charts.extend(await asyncio.to_thread(self._plot_combined_bar_charts, data))
            return {"charts": charts, "layout": "filtered"}

        if chart_type == "statistics":
            name, png = await asyncio.to_thread(self._plot_stats_table, analysis.get("statistics", []))
            if name:
                # charts.append({"name": name, "png": png, "type": "statistics", "title": "statistics"})
                charts.append({"html_path": name, "pdf_word_path": png})
            return {"charts": charts, "layout": "filtered"}

        if chart_type == "correlation":
            name, png = await asyncio.to_thread(self._plot_corr_heatmap, analysis.get("correlations", []))
            if name:
                # charts.append({"name": name, "png": png, "type": "correlation", "title": "correlation"})
                charts.append({"html_path": name, "pdf_word_path": png})
            return {"charts": charts, "layout": "filtered"}

        # 默认：生成折线 + 柱状 + 统计表 + 热力图 + 趋势
        charts.extend(await asyncio.to_thread(self._plot_line_charts, data))
        charts.extend(await asyncio.to_thread(self._plot_bar_charts, data))

        stats_name, stats_png = await asyncio.to_thread(
            self._plot_stats_table, analysis.get("statistics", [])
        )
        if stats_name:
            # charts.append({"name": stats_name, "png": stats_png, "type": "statistics", "title": "statistics"})
            charts.append({"html_path": stats_name, "pdf_word_path": stats_png})
        corr_name, corr_png = await asyncio.to_thread(
            self._plot_corr_heatmap, analysis.get("correlations", [])
        )
        if corr_name:
            # charts.append({"name": corr_name, "png": corr_png, "type": "correlation", "title": "correlation"})
            charts.append({"html_path": corr_name, "pdf_word_path": corr_png})
        for key, trend_data in analysis.get("trends", {}).items():
            trend_name, trend_png = await asyncio.to_thread(self._plot_trend, key, trend_data)
            if trend_name:
                charts.append({
                    "name": trend_name,
                    "png": trend_png,
                    "type": f"trend_{key}",
                    "title": f"trend_{key}"
                })

        return {"charts": charts, "layout": "default"}


# --- 数据分析代理类 ---
class DataAnalyst:
    def __init__(self, config: Dict[str, Any], visualizer_config: Dict[str, Any] = None):
        self.tools = {
            "cleaner": DataCleaner(),
            "analyzer": DataAnalyzer(),
            "visualizer": DataVisualizer(viz_config=visualizer_config)
        }

    async def process_all_tasks(self, context: DataContext) -> Dict[str, Any]:
        data = await self._load_data(context.data_source)
        # --- 关键：动态注入 y_pattern ---
        y_pat = context.requirements.get("y_pattern")
        if y_pat is not None:
            self.tools["visualizer"].y_pattern = y_pat

        # 下面保持原流程
        cleaning = await self.tools["cleaner"].clean_data(data)
        cleaned_df = pl.DataFrame(cleaning["cleaned_data"]["rows"])
        analysis = await self.tools["analyzer"].analyze_features(cleaned_df, context.requirements)
        chart_type = context.requirements.get("chart_type")
        viz = await self.tools["visualizer"].create_visualizations(cleaned_df, analysis, chart_type)
        result = {"cleaning": cleaning, "analysis": analysis, "visualization": viz}
        context.history.append(result)
        return result

    async def _load_data(self, data_source: Union[str, Dict[str, Any]]) -> pl.DataFrame:
        # 支持原生 JSON（data/rows）或 CSV 路径
        if isinstance(data_source, dict) and ("data" in data_source or "rows" in data_source):
            headers = data_source.get("headers", [])
            raw_rows = data_source.get("data", data_source.get("rows", []))
            cleaned_rows = []
            for row in raw_rows:
                cleaned = {}
                for k, v in row.items():
                    if v in ("", "null", None):
                        cleaned[k] = None
                    else:
                        try: cleaned[k] = float(v)
                        except: cleaned[k] = v
                cleaned_rows.append(cleaned)
            df = pl.DataFrame(cleaned_rows)
            if headers:
                df = df.select(headers)
            return df
        try:
            return pl.read_csv(data_source)
        except Exception as e:
            raise ValueError(f"无法加载数据源：{e}")

# --- 可调用服务 ---
class DataAnalysisService:
    def __init__(self, viz_config: Dict[str, Any] = None):
        self.analyst = DataAnalyst(config={}, visualizer_config=viz_config)

    async def run_analysis(self, data_source: Union[str, Dict[str, Any]], requirements: Dict[str, Any]) -> Dict[str, Any]:
        if isinstance(data_source, dict) and 'chart_type' in data_source:
            requirements['chart_type'] = data_source.pop('chart_type')
            if 'recommended_chart_type' in data_source:
                requirements['recommended_chart_type'] = data_source.pop('recommended_chart_type')
                # 如果 data_source 是 dict 且包含 y_pattern，就把它挪到 requirements
            if isinstance(data_source, dict) and "y_pattern" in data_source:
                requirements["y_pattern"] = data_source.pop("y_pattern")
        context = DataContext(data_source=data_source, requirements=requirements)
        # print(context)
        return await self.analyst.process_all_tasks(context)

    async def run_analysis_json(self, data_source: Union[str, Dict[str, Any]], requirements: Dict[str, Any]) -> str:
        result = await self.run_analysis(data_source, requirements)
        return json.dumps(result, indent=4, ensure_ascii=False)

def excel_to_json(
    path: str,
    sheet_idx: int = 0,
    skiprows: list = None,
    header_rows: int = 2
) -> str:
    """
    通用函数：将 Excel 文件转换为 JSON，并从首行提取合并单元格标题作为 sheet_name。

    参数:
    - path: Excel 文件路径
    - sheet_idx: 要读取的 sheet 索引（默认为第一个 sheet）
    - skiprows: 跳过的行索引列表，默认跳过首行标题
    - header_rows: 表头行数，默认两行（用于多级表头）

    返回:
    - JSON 字符串，包含 sheet_name、headers、rows
    """
    # 默认跳过首行
    skip = skiprows if skiprows is not None else [0]

    # 加载所有 sheet 名
    xls = pd.ExcelFile(path, engine='openpyxl')
    sheet_name_actual = xls.sheet_names[sheet_idx]

    # 1) 从首行中寻找第一个非空值作为标题
    title_df = pd.read_excel(
        xls,
        sheet_name=sheet_name_actual,
        header=None,
        nrows=1
    )
    raw_title = None
    for v in title_df.iloc[0].tolist():
        if pd.notna(v) and str(v).strip():
            raw_title = str(v).strip()
            break
    sheet_title = raw_title if raw_title else sheet_name_actual

    # 2) 读取内容，用后续 header_rows 行做表头
    df = pd.read_excel(
        xls,
        sheet_name=sheet_name_actual,
        skiprows=skip,
        header=list(range(header_rows)),
        engine='openpyxl'
    )

    # 3) 扁平化列名
    if isinstance(df.columns, pd.MultiIndex):
        cols = []
        last_top = None
        for tops in df.columns:
            parts = [str(p).strip() for p in tops]
            # 更新或继承顶级
            if parts[0] and not parts[0].startswith('Unnamed'):
                last_top = parts[0]
            else:
                parts[0] = last_top or parts[0]
            # 子级名称
            sub = parts[1] if len(parts) > 1 else ''
            # 合并名称
            cols.append(f"{parts[0]}_{sub}" if sub and not sub.startswith('Unnamed') else parts[0])
        df.columns = cols
    else:
        df.columns = [str(c).strip() for c in df.columns]

    # 4) 填充缺失，统一转 str
    df = df.fillna('').astype(str)

    # 5) 构造 JSON
    result = {
        'sheet_name': sheet_title,
        'headers': df.columns.tolist(),
        'rows': df.to_dict(orient='records')
    }
    # return json.dumps(result, ensure_ascii=False, indent=4)# 设置 indent=4，输出带有 4 个空格缩进的 JSON 格式
    return json.dumps(result, ensure_ascii=False)# 默认情况下没有缩进，紧凑输出

# --- 主程序示例 ---
async def main():
    # 提示用户输入文件路径或 JSON 数据
    inp = input("请输入Excel文件路径、CSV文件路径或JSON数据：").strip()

    # 尝试解析为 JSON 格式
    try:
        # 如果是 JSON 数据，直接加载
        data_source = json.loads(inp)
    except json.JSONDecodeError:
        try:
            # 如果是 Python 字面量格式（例如字典或列表），尝试加载
            data_source = ast.literal_eval(inp)
        except:
            # 否则认为是文件路径，判断文件类型
            file_path = inp
            if file_path.endswith(".csv"):
                # 如果是 CSV 文件，直接传入路径
                data_source = file_path
            elif file_path.endswith(".xlsx"):
                # 如果是 Excel 文件，转换为 JSON 格式
                data_source = excel_to_json(file_path)
                # data_source = ast.literal_eval(data_source)
                data_source = json.loads(data_source)
            else:
                raise ValueError("无法识别的文件类型或无效的 JSON 数据")
    print(f"解析后的数据源：{data_source}")
    # 提示用户输入 requirements 配置（可以是 JSON 字符串）
    requirements_input = input("请输入requirements配置（JSON格式）：").strip()

    # 解析用户输入的 requirements 配置
    try:
        requirements = json.loads(requirements_input)
    except json.JSONDecodeError:
        raise ValueError("无法解析的 JSON 格式，请检查输入的格式")

    viz_cfg = {
        "output_dir": "charts1",
        # "output_dir": "E:/PycharmProjects/report_template/test_data",
        "save_png": True,
        "y_pattern": "同比增减",  # ← 只画列名中包含 temp 的那些数值列
        "line": {"template": "plotly_dark", "width": 800, "height": 400},
        "bar": {"template": "ggplot2", "width": 600, "height": 350},
        "correlation": {"width": 700, "height": 700},
        "trend": {"template": "seaborn", "width": 900, "height": 450},
        "axis": {"tickfont": {"size": 12}, "titlefont": {"size": 14}}
    }
    # requirements = {
    #     "chart_type": "combined_line",
    #     # "y_pattern": "总量",
    #     "objective": "生成报告和图表"
    # }
    service = DataAnalysisService(viz_config=viz_cfg)
    result = await service.run_analysis(data_source, requirements)
    print(json.dumps(result, indent=4, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(main())
