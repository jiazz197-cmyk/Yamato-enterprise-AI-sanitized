from io import BytesIO

from openpyxl import load_workbook

from app.adapters.quotation.workbook import OpenpyxlQuotationWorkbookAdapter
from app.domain.quotation.value_objects import (
    QuotationDetailSheet,
    QuotationSummaryMeta,
    QuotationSummaryRow,
    QuotationWorkbookData,
)


def test_summary_rows_reference_detail_sheets_by_name_after_summary_only_row():
    workbook_data = QuotationWorkbookData(
        summary_sheet_name="汇总",
        summary_title="汇总",
        summary_meta=QuotationSummaryMeta(),
        summary_rows=[
            QuotationSummaryRow(
                part_no="A",
                name="外购件",
                quantity_display="1",
                unit_price=12,
                amount=12,
                detail_sheet_name="",
            ),
            QuotationSummaryRow(
                part_no="B",
                name="有明细组件",
                quantity_display="2",
                unit_price=99,
                amount=198,
                detail_sheet_name="组件B",
            ),
        ],
        detail_sheets=[
            QuotationDetailSheet(
                sheet_name="组件B",
                rows=[{"累计用量": 3, "单价": 4, "总价": 12}],
                total_amount=12,
            )
        ],
    )

    export = OpenpyxlQuotationWorkbookAdapter().export_workbook(workbook_data)
    wb = load_workbook(BytesIO(export.content), data_only=False)
    summary_ws = wb["汇总"]

    assert summary_ws["E12"].value == 12
    assert summary_ws["E13"].value == "='组件B'!C3"
    assert summary_ws["F13"].value == "=E13*D13"
    assert summary_ws["F10"].value == "=SUM(F12:F13)"
