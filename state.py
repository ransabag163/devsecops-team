"""Data shapes that agents return."""

from dataclasses import asdict, dataclass, field

REPORT_STATUSES = ("findings", "no_findings", "input_error")


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
