from app.services.scan_stages import ScanStage, next_stage, stages_from


def test_stages_from_start():
    assert stages_from(ScanStage.ENVELOPES) == [
        ScanStage.ENVELOPES, ScanStage.RECIPIENTS, ScanStage.DOCUMENTS, ScanStage.TEMPLATES]


def test_stages_from_middle_skips_finished():
    assert stages_from(ScanStage.DOCUMENTS) == [ScanStage.DOCUMENTS, ScanStage.TEMPLATES]


def test_completed_has_nothing_left():
    assert stages_from(ScanStage.COMPLETED) == []


def test_next_stage():
    assert next_stage(ScanStage.ENVELOPES) == ScanStage.RECIPIENTS
    assert next_stage(ScanStage.TEMPLATES) == ScanStage.COMPLETED