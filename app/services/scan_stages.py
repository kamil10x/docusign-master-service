"""Day 13: the stage state machine."""
from enum import Enum


class JobStatus:
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ScanStage(str, Enum):
    ENVELOPES = "envelopes"
    RECIPIENTS = "recipients"
    DOCUMENTS = "documents"
    TEMPLATES = "templates"
    COMPLETED = "completed"


STAGE_ORDER = [
    ScanStage.ENVELOPES,
    ScanStage.RECIPIENTS,
    ScanStage.DOCUMENTS,
    ScanStage.TEMPLATES,
]


def stages_from(stage: ScanStage) -> list[ScanStage]:
    """Stages still to run, starting at `stage` (empty list if already COMPLETED)."""
    if stage == ScanStage.COMPLETED:
        return []
    return STAGE_ORDER[STAGE_ORDER.index(stage):]


def next_stage(stage: ScanStage) -> ScanStage:
    idx = STAGE_ORDER.index(stage)
    return STAGE_ORDER[idx + 1] if idx + 1 < len(STAGE_ORDER) else ScanStage.COMPLETED