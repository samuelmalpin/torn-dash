from dataclasses import dataclass
from datetime import datetime


@dataclass
class UserSnapshot:
    timestamp: datetime
    level: int
    energy_current: int
    energy_max: int
    nerve_current: int
    nerve_max: int
    money: int
    points: int


@dataclass
class Alert:
    timestamp: datetime
    kind: str
    message: str
