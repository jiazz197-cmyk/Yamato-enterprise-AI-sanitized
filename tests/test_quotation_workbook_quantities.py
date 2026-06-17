from app.domain.quotation.workbook import build_quotation_workbook_data


def test_direct_u8_summary_quantity_uses_group_partids_mapping():
    workbook_data = build_quotation_workbook_data(
        uploaded_file_name="direct_u8.pdf",
        u8_result_by_type={
            "total": 1,
            "items": [
                {
                    "type": "根父件名称",
                    "partids": ["010101"],
                    "u8_parent_inv_codes": ["010101"],
                    "total": 1,
                    "items": [{"amount": 10}],
                }
            ],
        },
        summary_selection_items=None,
        partid_quantities={"010101": 5},
    )

    assert len(workbook_data.summary_rows) == 1
    assert workbook_data.summary_rows[0].quantity_display == "5"
    assert workbook_data.summary_rows[0].amount == 50


def test_project_mode_group_quantity_still_takes_precedence():
    workbook_data = build_quotation_workbook_data(
        uploaded_file_name="project.pdf",
        u8_result_by_type={
            "total": 1,
            "items": [
                {
                    "type": "项目子件",
                    "partids": ["010101"],
                    "u8_parent_inv_codes": ["010101"],
                    "quantity": 3,
                    "total": 1,
                    "items": [{"amount": 10}],
                }
            ],
        },
        summary_selection_items=None,
        partid_quantities={"010101": 5},
    )

    assert len(workbook_data.summary_rows) == 1
    assert workbook_data.summary_rows[0].quantity_display == "3.0"
    assert workbook_data.summary_rows[0].amount == 30
