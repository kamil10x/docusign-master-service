
from app.normalizers.document import DocumentNormalizer


def test_document_normalizer():
    records = [
        {
            "envelopeId": "env-101",
            "envelopeDocuments": [
                {
                    "documentId": "1",
                    "name": "Agreement.pdf",
                    "type": "content",
                    "pages": "5",
                    "order": "1",
                },
                {
                    "documentId": "2",
                    "name": "Invoice.pdf",
                    "type": "content",
                    "pages": "2",
                    "order": "2",
                },
            ],
        }
    ]

    result = DocumentNormalizer().normalize(records)

    rows = result["documents"]

    assert len(rows) == 2
    assert rows[0]["envelope_id"] == "env-101"
    assert rows[0]["document_id"] == "1"
    assert rows[0]["name"] == "Agreement.pdf"
    assert rows[0]["pages"] == 5
    assert rows[0]["order"] == 1


def test_document_normalizer_missing_optional_fields():
    records = [
        {
            "envelopeId": "env-102",
            "envelopeDocuments": [
                {
                    "documentId": "3",
                }
            ],
        }
    ]

    result = DocumentNormalizer().normalize(records)

    row = result["documents"][0]

    assert row["document_id"] == "3"
    assert row["name"] is None
    assert row["type"] is None
    assert row["pages"] is None
    assert row["order"] is None


def test_document_normalizer_invalid_records():
    records = [
        None,
        {"envelopeId": "env-103", "envelopeDocuments": "invalid"},
        {
            "envelopeId": "env-104",
            "envelopeDocuments": [
                None,
                {"name": "Missing ID.pdf"},
            ],
        },
    ]

    result = DocumentNormalizer().normalize(records)

    assert result["documents"] == []
