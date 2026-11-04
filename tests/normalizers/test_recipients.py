
from app.normalizers.recipient import RecipientNormalizer

n = RecipientNormalizer()


def normalize_one(raw):
    return n.normalize([raw])["recipients"]


def test_only_signers():
    raw = {
        "envelopeId": "e1",
        "signers": [{
            "recipientId": "1",
            "name": "A",
            "email": "a@x.com",
            "status": "completed",
            "routingOrder": "1",
            "signedDateTime": "2026-10-01T10:00:00Z"
        }]
    }

    rows = normalize_one(raw)

    assert len(rows) == 1
    assert rows[0]["recipient_type"] == "signer"
    assert rows[0]["routing_order"] == 1
    assert rows[0]["signed_at"] is not None


def test_signers_and_carbon_copies():
    raw = {
        "envelopeId": "e1",
        "signers": [{"recipientId": "1", "status": "sent"}],
        "carbonCopies": [
            {"recipientId": "2", "status": "delivered"},
            {"recipientId": "3", "status": "completed"}
        ]
    }

    rows = normalize_one(raw)

    assert [r["recipient_type"] for r in rows] == [
        "signer", "carbon_copy", "carbon_copy"
    ]
    assert all(r["envelope_id"] == "e1" for r in rows)


def test_declined_recipient():
    raw = {
        "envelopeId": "e1",
        "signers": [{
            "recipientId": "1",
            "status": "declined",
            "declinedDateTime": "2026-10-02T09:00:00Z",
            "declinedReason": "Wrong person"
        }]
    }

    rows = normalize_one(raw)
    r = rows[0]

    assert r["status"] == "declined"
    assert r["declined_reason"] == "Wrong person"
    assert r["declined_at"] is not None


def test_empty_recipients():
    assert normalize_one({"envelopeId": "e1"}) == []
    assert normalize_one({"envelopeId": "e1", "signers": []}) == []


def test_multiple_envelope_responses():
    records = [
        {
            "envelopeId": "e1",
            "signers": [{"recipientId": "1", "name": "A"}]
        },
        {
            "envelopeId": "e2",
            "signers": [{"recipientId": "2", "name": "B"}]
        }
    ]

    rows = n.normalize(records)["recipients"]

    assert len(rows) == 2
    assert [r["envelope_id"] for r in rows] == ["e1", "e2"]


def test_all_recipient_types():
    raw = {
        "envelopeId": "e1",
        "signers": [{"recipientId": "1"}],
        "carbonCopies": [{"recipientId": "2"}],
        "certifiedDeliveries": [{"recipientId": "3"}],
        "agents": [{"recipientId": "4"}],
        "editors": [{"recipientId": "5"}],
        "intermediaries": [{"recipientId": "6"}],
        "inPersonSigners": [{"recipientId": "7"}],
        "seals": [{"recipientId": "8"}],
        "witnesses": [{"recipientId": "9"}],
        "notaries": [{"recipientId": "10"}]
    }

    rows = normalize_one(raw)

    assert len(rows) == 10


def test_invalid_routing_order():
    raw = {
        "envelopeId": "e1",
        "signers": [
            {"recipientId": "1", "routingOrder": "invalid"}
        ]
    }

    rows = normalize_one(raw)

    assert rows[0]["routing_order"] is None
