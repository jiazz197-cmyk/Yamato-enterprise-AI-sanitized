"""Composition helpers for quotation execution use cases."""

from __future__ import annotations

from app.adapters.quotation.keyword_mapping import KeywordPayloadMappingAdapter
from app.adapters.quotation.ocr_structured import OcrStructuredInfoAdapter
from app.adapters.quotation.pdf_raster import PdfFirstPageRasterAdapter
from app.adapters.quotation.temp_object_storage import QuotationTempObjectStorageAdapter
from app.adapters.quotation.workbook import OpenpyxlQuotationWorkbookAdapter
from app.adapters.sqlserver_queries import PdmBomQueryAdapter, U8BomInventoryQueryAdapter
from app.usecases.quotation.build_workbook import BuildQuotationWorkbookUseCase
from app.usecases.quotation.execute_phase1 import ExecuteQuotationPhase1UseCase
from app.usecases.quotation.execute_phase2 import ExecuteQuotationPhase2UseCase


def build_execute_quotation_phase1_use_case() -> ExecuteQuotationPhase1UseCase:
    return ExecuteQuotationPhase1UseCase(
        pdf_raster=PdfFirstPageRasterAdapter(),
        temp_storage=QuotationTempObjectStorageAdapter(),
        ocr=OcrStructuredInfoAdapter(),
        keyword_mapping=KeywordPayloadMappingAdapter(),
        pdm_query=PdmBomQueryAdapter(),
    )


def build_execute_quotation_phase2_use_case() -> ExecuteQuotationPhase2UseCase:
    return ExecuteQuotationPhase2UseCase(u8_query=U8BomInventoryQueryAdapter())


def build_quotation_workbook_use_case() -> BuildQuotationWorkbookUseCase:
    return BuildQuotationWorkbookUseCase(render_port=OpenpyxlQuotationWorkbookAdapter())
