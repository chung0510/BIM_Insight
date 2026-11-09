from datetime import datetime
from uuid import UUID, uuid4
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ASSET_FILES = {"drawing.json": "drawing", "model.glb": "model", "model.json": "mapping", "converted.dxf": "converted_dxf", "inspection.json": "details"}


class ProjectCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)


class Project(BaseModel):
    id: str
    name: str
    description: str
    created_at: datetime
    owner_id: str | None = None
    owner_name: str = ""
    deleting: bool = False
    permissions: dict[str, bool] = Field(default_factory=dict)


class SourceContext(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    project_id: UUID
    logical_source: str = Field(min_length=1, max_length=120)
    revision: str = Field(default_factory=lambda: uuid4().hex, min_length=1, max_length=80)


class IssueReviewCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    state: Literal["unreviewed", "needs_fix", "intentional", "insufficient_data"]
    reviewer: str = Field(min_length=1, max_length=80)
    note: str = Field(default="", max_length=2000)
    expected_revision: int = Field(ge=0, le=1000000)

    @model_validator(mode="after")
    def explain_intentional(self):
        if self.state == "intentional" and not self.note:
            raise ValueError("A design-intent review needs an explanation")
        return self


class CaseReviewCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    label: Literal["unreviewed", "intersection", "clearance", "no_clash", "insufficient_data"]
    reviewer: str = Field(min_length=1, max_length=80)
    note: str = Field(min_length=1, max_length=2000)
    expected_revision: int = Field(ge=0, le=1000000)
