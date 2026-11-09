import pytest
import ifcopenshell
import numpy as np
from types import SimpleNamespace

from test_ifc_probe import small_ifc
from test_api import AUTH
from test_inspections import inspection_client


@pytest.mark.parametrize('available_gib,cores,expected', [
    (2, 8, 1), (3.49, 8, 1), (3.5, 8, 2), (4, 1, 1), (4, None, 1), (12, 8, 2),
])
def test_import_parallelism_respects_ram_and_physical_cores(monkeypatch, available_gib, cores, expected):
    import psutil
    from app.limits import ifc_geometry_threads

    monkeypatch.setattr(psutil, 'virtual_memory', lambda: SimpleNamespace(total=16 * 1024**3, available=available_gib * 1024**3))
    monkeypatch.setattr(psutil, 'cpu_count', lambda logical=True: cores)

    assert ifc_geometry_threads() == expected


def test_import_selects_parallelism_before_parsing_and_passes_it_to_iterator(small_ifc, monkeypatch):
    import app.ifc as importer
    import ifcopenshell.geom

    order = []
    monkeypatch.setattr(importer, 'ifc_geometry_threads', lambda: order.append('threads') or 2)
    original_open = ifcopenshell.open
    def parsed(*args, **kwargs):
        order.append('parse')
        return original_open(*args, **kwargs)
    monkeypatch.setattr(ifcopenshell, 'open', parsed)
    original = ifcopenshell.geom.iterator
    used = []
    def measured(settings, model, threads, **kwargs):
        used.append(threads)
        return original(settings, model, threads, **kwargs)
    monkeypatch.setattr(ifcopenshell.geom, 'iterator', measured)
    report = importer.inspect_ifc(small_ifc[0])

    assert report['status'] == 'completed'
    assert used == [2]
    assert order == ['threads', 'parse']
    assert report['geometry_settings']['threads'] == 2


@pytest.mark.parametrize('name,expected', [
    ('ARK_NordicLCA_Housing_Concrete_BuildingPermit_Revit.ifc', 'ARCH'),
    ('MEP_HVAC_NordicLCA_Housing_Concrete_BuildingPermit.ifc', 'MEP'),
    ('MEP_ELE_NordicLCA_Housing_Concrete_BuildingPermit.ifc', 'MEP'),
    ('STRUC_NordicLCA_Housing_Concrete_BuildingPermit.ifc', 'STR'),
    ('DEMO_ARCH.ifc', 'ARCH'),
    ('archived-building.ifc', 'OTHER'),
    ('ARCH_STR_combined.ifc', 'OTHER'),
    ('unknown.ifc', 'OTHER'),
])
def test_discipline_is_inferred_conservatively_without_user_input(name, expected):
    from app.inspections import infer_discipline

    assert infer_discipline(name) == expected


def test_upload_without_discipline_uses_original_filename(tmp_path, small_ifc):
    with inspection_client(tmp_path / 'app') as client:
        report = client.post('/api/inspections', files={'file': ('ARK_original.ifc', small_ifc[0].read_bytes())}, headers=AUTH).json()
    assert report['status'] == 'completed'
    assert report['discipline'] == 'ARCH'


def test_shared_geometry_is_imported_without_rebuilding_every_product(tmp_path, small_ifc, monkeypatch):
    from app.ifc import inspect_ifc
    import ifcopenshell.geom

    path, guid = small_ifc
    model = ifcopenshell.open(str(path))
    wall = model.by_guid(guid)
    for index in range(100):
        model.create_entity('IfcWall', GlobalId=ifcopenshell.guid.new(), Name=f'Shared geometry {index}', ObjectPlacement=wall.ObjectPlacement, Representation=wall.Representation)
    model.write(str(path))
    def redundant_rebuild(*args, **kwargs):
        raise AssertionError('Do not compile the same representation once per product')
    monkeypatch.setattr(ifcopenshell.geom, 'create_shape', redundant_rebuild)
    assets = tmp_path / 'assets'
    assets.mkdir()
    result = inspect_ifc(path, assets)
    assert result['status'] == 'completed', result['diagnostics']
    assert result['element_count'] == 101
    assert len({item['guid'] for item in result['elements']}) == 101
    assert all(item['bounds_m'] == result['elements'][0]['bounds_m'] for item in result['elements'])
    assert result['viewer_available'] and result['mapping_available']
    assert result['viewer_optimization']['version'] == 1
    assert result['viewer_optimization']['after_bytes'] == (assets / 'model.glb').stat().st_size


def test_large_preview_releases_conversion_cache_between_batches(tmp_path, small_ifc, monkeypatch):
    import weakref
    import ifcopenshell.geom
    from app.ifc import inspect_ifc

    path, guid = small_ifc
    model = ifcopenshell.open(str(path))
    wall = model.by_guid(guid)
    for index in range(512):
        model.create_entity('IfcWall', GlobalId=ifcopenshell.guid.new(), Name=f'Preview {index}',
                            ObjectPlacement=wall.ObjectPlacement, Representation=wall.Representation)
    model.write(str(path))
    original, sizes, references = ifcopenshell.geom.iterator, [], []
    def bounded(settings, model, threads, **kwargs):
        assert not references or references[-1]() is None, 'Release native cache before starting another batch'
        sizes.append(len(kwargs['include']))
        iterator = original(settings, model, threads, **kwargs)
        references.append(weakref.ref(iterator))
        return iterator
    monkeypatch.setattr(ifcopenshell.geom, 'iterator', bounded)
    assets = tmp_path / 'assets'
    assets.mkdir()
    result = inspect_ifc(path, assets)
    assert result['status'] == 'completed', result['diagnostics']
    assert result['element_count'] == 513
    assert len(sizes) > 1 and max(sizes) <= 512
    assert all(reference() is None for reference in references)
    assert result['viewer_available'] and result['mapping_available']


@pytest.mark.parametrize('failure', ['construction', 'advance'])
def test_failed_preview_batch_does_not_skip_later_healthy_elements(tmp_path, small_ifc, monkeypatch, failure):
    import weakref
    import ifcopenshell.geom
    from app.ifc import inspect_ifc
    monkeypatch.setattr('app.ifc.ifc_geometry_batch_size', lambda: 512)

    path, guid = small_ifc
    model = ifcopenshell.open(str(path))
    wall = model.by_guid(guid)
    for index in range(512):
        last = model.create_entity('IfcWall', GlobalId=ifcopenshell.guid.new(), Name=f'Preview {index}',
                                   ObjectPlacement=wall.ObjectPlacement, Representation=wall.Representation)
    last_guid = last.GlobalId
    model.write(str(path))
    original, sizes, references = ifcopenshell.geom.iterator, [], []
    class FailingIterator:
        def __init__(self, iterator):
            self.iterator = iterator
        def __iter__(self):
            yield next(iter(self.iterator))
            raise RuntimeError('test native iterator failure')
    def measured(settings, model, threads, **kwargs):
        assert not references or references[-1]() is None
        sizes.append(len(kwargs['include']))
        if len(sizes) == 1 and failure == 'construction':
            raise RuntimeError('test native constructor failure')
        iterator = original(settings, model, threads, **kwargs)
        if len(sizes) == 1:
            iterator = FailingIterator(iterator)
        references.append(weakref.ref(iterator))
        return iterator
    monkeypatch.setattr(ifcopenshell.geom, 'iterator', measured)
    assets = tmp_path / 'assets'
    assets.mkdir()
    result = inspect_ifc(path, assets)
    assert sizes == [512, 1]
    assert all(reference() is None for reference in references)
    assert result['status'] == 'completed'
    assert last_guid in {element['guid'] for element in result['elements']}
    assert result['element_count'] == 513
    assert result['excluded_count'] == 0
    assert result['geometry_fallback_count'] == (512 if failure == 'construction' else 511)
    assert result['viewer_available'] and result['mapping_available']


def test_world_bounds_cover_all_batches_and_preserve_large_rotated_coordinates():
    from app.ifc import world_bounds

    vertices = np.zeros((70_000, 3))
    vertices[0] = [-2, -3, -4]
    vertices[-1] = [5, 6, 7]
    matrix = np.array([[0., -1, 0, 1_000_000], [1, 0, 0, 2_000_000], [0, 0, 1, 3], [0, 0, 0, 1]])
    shape = SimpleNamespace(transformation_buffer=matrix.tobytes(order='F'))
    geometry = SimpleNamespace(verts_buffer=vertices.tobytes())
    bounds = world_bounds(shape, geometry)
    assert bounds['min'] == pytest.approx([999994, 1999998, -1])
    assert bounds['max'] == pytest.approx([1000003, 2000005, 10])


def test_import_declares_preview_quality_separate_from_clash_geometry(small_ifc, tmp_path):
    from app.ifc import inspect_ifc

    result = inspect_ifc(small_ifc[0])
    assert result['geometry_settings']['linear_deflection_m'] == .001
    assert result['geometry_settings']['scope'] == 'import_preview_only'
    assert result['geometry_settings']['clash_geometry'] == 'rebuilt_from_source'


def test_iterator_failure_is_reported_as_missing_geometry_instead_of_losing_metadata(small_ifc, monkeypatch):
    from app.ifc import inspect_ifc
    import ifcopenshell.geom

    def failed_iterator(*args, **kwargs):
        raise RuntimeError('A malformed geometry failed inside the iterator')
    monkeypatch.setattr(ifcopenshell.geom, 'iterator', failed_iterator)
    monkeypatch.setattr(ifcopenshell.geom, 'create_shape', failed_iterator)
    result = inspect_ifc(small_ifc[0])
    assert result['status'] == 'partial'
    assert result['total_element_count'] == 1
    assert result['excluded_count'] == 1
    assert {'guid': small_ifc[1], 'code': 'geometry_failed'} in result['diagnostics']
    assert result['geometry_failures'][0]['detail'] == 'A malformed geometry failed inside the iterator'


def test_unemitted_preview_geometry_falls_back_without_rebuilding_successful_items(small_ifc, monkeypatch):
    from app.ifc import inspect_ifc
    import ifcopenshell.geom

    monkeypatch.setattr(ifcopenshell.geom, 'iterator', lambda *args, **kwargs: iter(()))
    result = inspect_ifc(small_ifc[0])
    assert result['status'] == 'completed'
    assert result['element_count'] == 1
    assert result['geometry_fallback_count'] == 1


def test_failed_physical_metadata_is_not_counted_as_successfully_emitted(small_ifc, monkeypatch):
    import ifcopenshell.util.element
    from app.ifc import inspect_ifc

    path, guid = small_ifc
    model = ifcopenshell.open(str(path))
    wall = model.by_guid(guid)
    model.create_entity('IfcWall', GlobalId=ifcopenshell.guid.new(), ObjectPlacement=wall.ObjectPlacement, Representation=wall.Representation)
    model.write(str(path))
    def invalid_containment(product):
        if product.GlobalId == guid:
            raise RecursionError('Cyclic containment')
        return None
    monkeypatch.setattr(ifcopenshell.util.element, 'get_container', invalid_containment)

    report = inspect_ifc(path)

    assert report['status'] == 'partial'
    assert report['element_count'] == 1
    assert report['excluded_count'] == 1
    assert {'guid': guid, 'code': 'geometry_failed'} in report['diagnostics']


@pytest.mark.parametrize('threads', [1, 2])
def test_fast_preview_preserves_the_real_opening_cut(tmp_path, monkeypatch, threads):
    import app.ifc as importer
    import ifcopenshell.util.shape
    from app.demo import demo_model

    source = tmp_path / 'opening.ifc'
    source.write_text(demo_model('ARCH')['content'], encoding='utf-8')
    original = importer.world_bounds
    monkeypatch.setattr(importer, 'ifc_geometry_threads', lambda: threads)
    wall_volumes = []
    def measured(shape, geometry):
        if shape.type == 'IfcWall':
            wall_volumes.append(ifcopenshell.util.shape.get_volume(geometry))
        return original(shape, geometry)
    monkeypatch.setattr(importer, 'world_bounds', measured)
    report = importer.inspect_ifc(source)
    assert report['status'] == 'completed'
    assert report['element_count'] == 1
    assert report['subtraction_count'] == 1
    assert wall_volumes == pytest.approx([4 * .4 * 3 - .4 * .4 * .6])


@pytest.mark.parametrize('invalid_body', ['empty', 'curve_only'])
def test_invalid_opening_is_reported_instead_of_silently_leaving_host_uncut(tmp_path, invalid_body):
    from app.demo import demo_model
    from app.ifc import inspect_ifc

    model = ifcopenshell.file.from_string(demo_model('ARCH')['content'])
    opening = model.by_type('IfcOpeningElement')[0]
    body = opening.Representation.Representations[0]
    body.Items = () if invalid_body == 'empty' else (model.create_entity(
        'IfcPolyline', Points=(model.create_entity('IfcCartesianPoint', Coordinates=(0., 0., 0.)),
                               model.create_entity('IfcCartesianPoint', Coordinates=(1., 0., 0.)))),)
    source = tmp_path / f'opening-{invalid_body}.ifc'
    model.write(str(source))

    report = inspect_ifc(source)

    assert report['status'] == 'partial'
    assert report['excluded_count'] == 2  # Invalid opening also makes its host unsafe to assess.
    assert {'guid': opening.GlobalId, 'code': 'ifc_body_nonphysical'} in report['diagnostics']
    assert not any(item['geometry_status'] == 'built' for item in report['inventory'])


def test_preview_uses_physical_body_instead_of_solid_clearance(small_ifc):
    import ifcopenshell.api.context
    import ifcopenshell.api.geometry
    from app.ifc import inspect_ifc

    path, guid = small_ifc
    model = ifcopenshell.open(str(path))
    wall = model.by_guid(guid)
    context = next(item for item in model.by_type('IfcGeometricRepresentationContext') if not item.is_a('IfcGeometricRepresentationSubContext'))
    clearance_context = ifcopenshell.api.context.add_context(model, context_type='Model', context_identifier='Clearance', target_view='MODEL_VIEW', parent=context)
    clearance = ifcopenshell.api.geometry.add_wall_representation(model, context=clearance_context, length=8, height=5, thickness=2)
    clearance.RepresentationIdentifier = 'Clearance'
    wall.Representation.Representations = (*wall.Representation.Representations, clearance)
    model.write(str(path))
    original = path.read_bytes()
    report = inspect_ifc(path)
    assert report['element_count'] == 1
    assert len({element['guid'] for element in report['elements']}) == 1
    assert report['elements'][0]['bounds_m']['max'] == pytest.approx([14, 20.2, 3])
    assert path.read_bytes() == original


def test_multiple_body_representations_keep_all_geometry_under_one_guid(small_ifc, tmp_path):
    import json
    import ifcopenshell.api.geometry
    from app.ifc import inspect_ifc

    path, guid = small_ifc
    model = ifcopenshell.open(str(path))
    wall = model.by_guid(guid)
    body = wall.Representation.Representations[0]
    extra = ifcopenshell.api.geometry.add_wall_representation(model, context=body.ContextOfItems, length=1, height=1, thickness=.1)
    extra.Items[0].Position.Location.Coordinates = (10000., 0., 0.)
    wall.Representation.Representations = (body, extra)
    model.write(str(path))
    assets = tmp_path / 'body-assets'
    assets.mkdir()
    report = inspect_ifc(path, assets)
    assert report['status'] == 'completed', report['diagnostics']
    assert report['element_count'] == 1
    assert report['elements'][0]['triangle_count'] == 24
    assert report['elements'][0]['bounds_m']['max'] == pytest.approx([21, 20.2, 3])
    mapping = json.loads((assets / 'model.json').read_text(encoding='utf-8'))
    assert [element['guid'] for element in mapping['elements']] == [guid]


def test_opening_body_selection_includes_ancestors_and_rejects_missing_geometry(small_ifc):
    import ifcopenshell.api.root
    import ifcopenshell.api.geometry
    from app.ifc import select_opening_bodies

    model = ifcopenshell.open(str(small_ifc[0]))
    child = model.by_guid(small_ifc[1])
    parent = ifcopenshell.api.root.create_entity(model, ifc_class='IfcWall', name='Opening host ancestor')
    model.create_entity('IfcRelAggregates', GlobalId=ifcopenshell.guid.new(), RelatingObject=parent, RelatedObjects=(child,))
    opening = ifcopenshell.api.root.create_entity(model, ifc_class='IfcOpeningElement')
    first = child.Representation.Representations[0]
    extra = ifcopenshell.api.geometry.add_wall_representation(model, context=first.ContextOfItems, length=.2, height=.2, thickness=.2)
    opening.Representation = model.create_entity('IfcProductDefinitionShape', Representations=(first, extra))
    model.create_entity('IfcRelVoidsElement', GlobalId=ifcopenshell.guid.new(), RelatingBuildingElement=parent, RelatedOpeningElement=opening)
    select_opening_bodies(model, [child])
    assert len(opening.Representation.Representations) == 1
    assert len(opening.Representation.Representations[0].Items) == 2
    opening.Representation = None
    with pytest.raises(ValueError, match='ifc_body_missing'):
        select_opening_bodies(model, [child])


def test_body_representations_with_different_frames_are_not_silently_combined(small_ifc):
    import ifcopenshell.api.geometry
    from app.ifc import select_physical_body

    model = ifcopenshell.open(str(small_ifc[0]))
    product = model.by_guid(small_ifc[1])
    body = product.Representation.Representations[0]
    placement = model.create_entity('IfcAxis2Placement3D', Location=model.create_entity('IfcCartesianPoint', Coordinates=(1000., 0., 0.)))
    other_context = model.create_entity('IfcGeometricRepresentationContext', ContextType='Model', CoordinateSpaceDimension=3, Precision=1e-5, WorldCoordinateSystem=placement)
    extra = ifcopenshell.api.geometry.add_wall_representation(model, context=other_context, length=1, height=1, thickness=.1)
    extra.RepresentationIdentifier = 'Body'
    product.Representation.Representations = (body, extra)
    with pytest.raises(ValueError, match='ifc_body_context_ambiguous'):
        select_physical_body(model, product)


