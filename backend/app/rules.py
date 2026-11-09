from typing import Annotated, Literal
import hashlib

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator
from app.limits import CLASH_MODELS


ReportId = Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]


class ClashRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_ids: list[ReportId] = Field(min_length=2, max_length=CLASH_MODELS)
    mode: Literal["hard", "clearance"] = "hard"
    tolerance_mm: FiniteFloat = Field(default=1, ge=.1, le=10)
    clearance_mm: FiniteFloat = Field(default=50, ge=1, le=500)
    coordinates_confirmed: bool = False
    shared_references_confirmed: bool = False
    link_id: ReportId | None = None

    @field_validator("model_ids")
    @classmethod
    def unique_models(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("clash_duplicate_source")
        return value


def issue_group_key(a, b, kind):
    references = sorted(f"{item['source_id']}:{item.get('canonical_guid') or item['guid']}" for item in [a, b])
    return hashlib.sha256(("|".join(references) + "|" + kind).encode()).hexdigest()[:24]


def canonical_reference(product):
    current, seen = product, {product.id()}
    if product.is_a("IfcBuildingElementPart") or product.is_a("IfcStairFlight") or product.is_a("IfcMember") or product.is_a("IfcPlate"):
        while True:
            relations = [*current.Decomposes, *getattr(current, "Nests", [])]
            if not relations:
                break
            parent = relations[0].RelatingObject
            if parent.id() in seen or not parent.is_a("IfcElement"):
                break
            seen.add(parent.id())
            current = parent
    family = next((kind for kind in ["IfcWall", "IfcSlab", "IfcBeam", "IfcColumn", "IfcCurtainWall", "IfcStair"] if current.is_a(kind)), current.is_a())
    return current.GlobalId, family


def has_represented_ancestor(product, represented_ids):
    pending = [product]
    seen = {product.id()}
    while pending:
        item = pending.pop()
        for relation in [*item.Decomposes, *getattr(item, "Nests", [])]:
            parent = relation.RelatingObject
            if parent.id() in seen:
                continue
            seen.add(parent.id())
            if parent.id() in represented_ids:
                return True
            pending.append(parent)
    return False
