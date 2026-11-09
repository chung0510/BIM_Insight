"""Generate disposable, explicitly synthetic inputs for the in-app checks."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import ifcopenshell
import ezdxf
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from backend.research.make_fixture import make_fixture


directory = Path(sys.argv[1])
directory.mkdir(parents=True, exist_ok=False)
make_fixture(directory)
for name, text in [("drawing.pdf", True), ("blank.pdf", False)]:
    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    if text:
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)}),
        })
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 50 750 Td (ARCH Level 1 - grid A) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(stream)
    with (directory / name).open("xb") as output:
        writer.write(output)

model = ifcopenshell.open(str(directory / "ARCH.ifc"))
axes = []
for tag, coordinates in [("1", [(0., 0., 0.), (0., 10000., 0.)]), ("A", [(0., 0., 0.), (10000., 0., 0.)])]:
    curve = model.create_entity("IfcPolyline", Points=[model.create_entity("IfcCartesianPoint", Coordinates=p) for p in coordinates])
    axes.append(model.create_entity("IfcGridAxis", AxisTag=tag, AxisCurve=curve, SameSense=True))
grid = model.create_entity("IfcGrid", GlobalId=ifcopenshell.guid.new(), UAxes=[axes[0]], VAxes=[axes[1]])
model.write(str(directory / "ARCH.ifc"))
cad = ezdxf.new("R2018", units=4)
cad.layers.add("S-GRID", color=1)
cad.layers.add("A-WALL", color=7)
cad.modelspace().add_line((0, 0), (0, 10000), dxfattribs={"layer": "S-GRID"})
cad.modelspace().add_line((0, 0), (10000, 0), dxfattribs={"layer": "S-GRID"})
cad.modelspace().add_line((0, 0), (4000, 0), dxfattribs={"layer": "A-WALL"})
cad.modelspace().add_mtext(r"T\U+1EA6NG 1", dxfattribs={"insert": (1000, 1000), "char_height": 250, "layer": "A-WALL"})
cad.saveas(directory / "floor.dxf")
wall = model.by_type("IfcWall")[0]
for index in range(5000):
    model.create_entity(
        "IfcWall", GlobalId=ifcopenshell.guid.new(), Name=f"Synthetic close test {index}",
        ObjectPlacement=wall.ObjectPlacement, Representation=wall.Representation,
    )
model.write(str(directory / "close-during-check.ifc"))
assert len(model.by_type("IfcWall")) == 5001
