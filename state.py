"""Data shapes that agents return."""

from dataclasses import asdict, dataclass, field

REPORT_STATUSES = ("findings", "no_findings", "input_error")
PROPOSAL_STATUSES = ("proposed", "skipped")
FIX_REPORT_STATUSES = ("fixes", "no_fixes", "input_error")
VERDICTS = ("approve", "retry", "human")
VERIFICATION_REPORT_STATUSES = ("verified", "no_proposals", "input_error")


@dataclass
class Finding:
    id: str
    cwe: str
    rule: str
    line: int
    evidence: str
    verdict: str
    reason: str

    def to_dict(self):
        return asdict(self)


@dataclass
class FindingsReport:
    file: str
    status: str
    findings: list = field(default_factory=list)
    error: str | None = None

    def __post_init__(self):
        if self.status not in REPORT_STATUSES:
            raise ValueError(f"unknown status: {self.status}")

    def to_dict(self):
        return {
            "file": self.file,
            "status": self.status,
            "findings": [f.to_dict() for f in self.findings],
            "error": self.error,
        }


@dataclass
class PatchProposal:
    """One suggested fix for one finding. The diff is always made by the application."""
    finding_id: str
    status: str
    start_line: int | None = None
    end_line: int | None = None
    replacement: str | None = None
    diff: str | None = None
    explanation: str = ""

    def __post_init__(self):
        if self.status not in PROPOSAL_STATUSES:
            raise ValueError(f"unknown status: {self.status}")

    def to_dict(self):
        return asdict(self)


@dataclass
class FixReport:
    file: str
    status: str
    proposals: list = field(default_factory=list)
    error: str | None = None

    def __post_init__(self):
        if self.status not in FIX_REPORT_STATUSES:
            raise ValueError(f"unknown status: {self.status}")

    def to_dict(self):
        return {
            "file": self.file,
            "status": self.status,
            "proposals": [p.to_dict() for p in self.proposals],
            "error": self.error,
        }


@dataclass
class Verification:
    """The tester's result for one proposal.

    closed, new_findings, works and attack always come from the tools, never
    from the model. status is how the tester's run ended (final, invalid_action, ...).
    """
    finding_id: str
    closed: bool | None
    new_findings: list | None
    works: str
    attack: str
    verdict: str
    feedback: str
    status: str

    def __post_init__(self):
        if self.verdict not in VERDICTS:
            raise ValueError(f"unknown verdict: {self.verdict}")

    def to_dict(self):
        return asdict(self)


@dataclass
class VerificationReport:
    file: str
    status: str
    verifications: list = field(default_factory=list)
    error: str | None = None

    def __post_init__(self):
        if self.status not in VERIFICATION_REPORT_STATUSES:
            raise ValueError(f"unknown status: {self.status}")

    def to_dict(self):
        return {
            "file": self.file,
            "status": self.status,
            "verifications": [v.to_dict() for v in self.verifications],
            "error": self.error,
        }
