"""All ORM models.

Alembic's autogenerate only sees tables that have been imported, so every model
module must be re-exported here. A table added to a module but missing from
this list simply never appears in a migration.
"""

from app.db.models.base import SCHEMA, Base
from app.db.models.catalog import (
    Circuit,
    Constructor,
    Driver,
    DriverSeason,
    Meeting,
    Season,
    Session,
)
from app.db.models.enums import (
    ACTIVE_STATUSES,
    FINISHED_STATUSES,
    JobStage,
    JobStatus,
    ReportTrigger,
    ReportType,
    SessionType,
)
from app.db.models.jobs import IngestionJob
from app.db.models.reports import Report
from app.db.models.standings import ConstructorStanding, DriverStanding, StandingsFetch
from app.db.models.timing import Lap, PitStop, RaceControlEvent, SessionResult

__all__ = [
    "ACTIVE_STATUSES",
    "FINISHED_STATUSES",
    "SCHEMA",
    "Base",
    "Circuit",
    "Constructor",
    "ConstructorStanding",
    "Driver",
    "DriverSeason",
    "DriverStanding",
    "IngestionJob",
    "JobStage",
    "JobStatus",
    "Lap",
    "Meeting",
    "PitStop",
    "RaceControlEvent",
    "Report",
    "ReportTrigger",
    "ReportType",
    "Season",
    "Session",
    "SessionResult",
    "SessionType",
    "StandingsFetch",
]
