import os
import pytest
from clinic_inventory import db
from clinic_inventory.errors import AppError
from clinic_inventory.services import catalog, barcodes
from .conftest import user


def test_barcode_encoding_and_decoding():
    # Representative codes
    test_codes = [
        "IT-00001",
        "IT-00002",
        "MED-9988",
        "1234567890",
        "SURG-BOX-10"
    ]
    for code in test_codes:
        # Verify encodable and decodable
        assert barcodes.verify_code128_encodable(code) is True

        from reportlab.graphics.barcode.code128 import Code128
        b = Code128(code)
        b.validate()
        b.encode()
        decoded = barcodes.decode_code128_symbols(b.encoded)
        assert decoded == code


def test_item_code_permanent_and_barcode_uniqueness(env):
    admin = user(env.ids["admin"])

    # Create item with barcode
    with db.session_scope() as s:
        it = catalog.create_item(s, admin, "قفازات جراحية", "علبة", barcode="6221234567890")
        assert it.code == "IT-00002"
        assert it.barcode == "6221234567890"
        it_id = it.id

    # Duplicate barcode must be rejected
    with pytest.raises(AppError):
        with db.session_scope() as s:
            catalog.create_item(s, admin, "قفازات أخرى", "علبة", barcode="6221234567890")

    # Item code cannot be modified
    with pytest.raises(AppError) as excinfo:
        with db.session_scope() as s:
            catalog.update_item(s, admin, it_id, code="MODIFIED-001")
    assert "لا يمكن تغيير كود الصنف" in str(excinfo.value)

    # Search by barcode and manual code
    with db.session_scope() as s:
        res1 = catalog.search_items(s, "6221234567890")
        assert len(res1) == 1
        assert res1[0].id == it_id

        res2 = catalog.search_items(s, "IT-00002")
        assert len(res2) == 1
        assert res2[0].id == it_id


def test_label_pdf_generation(env, tmp_path):
    admin = user(env.ids["admin"])
    with db.session_scope() as s:
        it = catalog.create_item(s, admin, "كحول إيثيلي 70%", "زجاجة", barcode="77889900")
        it_dict = {"code": it.code, "name": it.name, "barcode": it.barcode}

    # Single label
    single_pdf = str(tmp_path / "single_label.pdf")
    barcodes.generate_single_label_pdf(single_pdf, it_dict)
    assert os.path.exists(single_pdf)
    assert os.path.getsize(single_pdf) > 500

    # Sheet of labels
    sheet_pdf = str(tmp_path / "sheet_labels.pdf")
    barcodes.generate_sheet_labels_pdf(sheet_pdf, [it_dict], copies_per_item=6)
    assert os.path.exists(sheet_pdf)
    assert os.path.getsize(sheet_pdf) > 1000
