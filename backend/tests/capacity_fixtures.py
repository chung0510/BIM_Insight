"""Generated geometry for capacity regression; never a research ground-truth dataset."""
from pathlib import Path
import sys

import ifcopenshell
import ifcopenshell.api.context
import ifcopenshell.api.geometry
import ifcopenshell.api.project
import ifcopenshell.api.root
import ifcopenshell.api.unit


def capacity_files(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    files = []
    for index in range(6):
        model = ifcopenshell.api.project.create_file(version="IFC4")
        ifcopenshell.api.root.create_entity(model, ifc_class="IfcProject", name="Capacity regression only")
        unit = ifcopenshell.api.unit.add_si_unit(model, unit_type="LENGTHUNIT", prefix="MILLI")
        ifcopenshell.api.unit.assign_unit(model, units=[unit])
        context = ifcopenshell.api.context.add_context(model, context_type="Model")
        body = ifcopenshell.api.context.add_context(model, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=context)
        shape = ifcopenshell.api.geometry.add_wall_representation(model, context=body, length=4, height=3, thickness=.2)
        representation = model.create_entity("IfcProductDefinitionShape", Representations=(shape,))
        parent = ifcopenshell.api.root.create_entity(model, ifc_class="IfcWall", name="Capacity aggregate") if index < 2 else None
        children = []
        for number in range(1100 if index < 2 else 1):
            position = (float(number % 34 * 10000 + (1000 if index == 1 else 0)), float(number // 34 * 10000 + (50 if index == 1 else 0) - (index * 10000 if index >= 2 else 0)), 200. if index == 1 else 0.)
            placement = model.create_entity("IfcLocalPlacement", RelativePlacement=model.create_entity("IfcAxis2Placement3D", Location=model.create_entity("IfcCartesianPoint", Coordinates=position)))
            children.append(model.create_entity("IfcBuildingElementPart" if parent else "IfcWall", GlobalId=ifcopenshell.guid.new(), Name=f"Capacity {index + 1} wall {number + 1}", ObjectPlacement=placement, Representation=representation))
        if parent:
            model.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(), RelatingObject=parent, RelatedObjects=children)
        path = directory / f"CAPACITY_{index + 1:02}.ifc"
        model.write(str(path))
        files.append(path)
    from test_inspections import pdf_bytes
    for index in range(7):
        path = directory / f"DRAWING_{index + 1:02}.pdf"
        path.write_bytes(pdf_bytes())
        files.append(path)
    return files


if __name__ == "__main__":
    capacity_files(sys.argv[1])
