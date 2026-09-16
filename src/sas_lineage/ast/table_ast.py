"""Table-level evidence; a literal name is not proof that a step executed."""
from dataclasses import asdict, dataclass
from typing import Optional


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    source_line: Optional[int] = None

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class TableReference:
    name: str
    access: str
    source_line: int
    resolution: str = "literal"
    reason: Optional[str] = None

    def to_dict(self):
        return asdict(self)
