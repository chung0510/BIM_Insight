import hashlib
import json
from pathlib import Path

import ifcopenshell
import ifcopenshell.api.geometry
import pytest

from app.ifc import inspect_ifc
from test_ifc_probe import small_ifc
from test_clash import demo_sources, options
from test_projects import workspace, project
from test_api import AUTH


def add_reference(model, owner, *, mapped=False, identifier='Annotation', ifc_class='IfcBuildingElementProxy'):
    line = model.create_entity('IfcPolyline', Points=(
        model.create_entity('IfcCartesianPoint', Coordinates=(0., 0., 0.)),
        model.create_entity('IfcCartesianPoint', Coordinates=(1000., 0., 0.))))
    body = model.create_entity('IfcShapeRepresentation', ContextOfItems=owner.Representation.Representations[0].ContextOfItems,
                               RepresentationIdentifier=identifier, RepresentationType='GeometricSet',
                               Items=(model.create_entity('IfcGeometricSet', Elements=(line,)),))
    if mapped:
        body = ifcopenshell.api.geometry.map_representation(model, representation=body)
        body.RepresentationIdentifier = identifier
    return model.create_entity(ifc_class, GlobalId=ifcopenshell.guid.new(), Name='Arbitrary name',
                               ObjectPlacement=owner.ObjectPlacement,
                               Representation=model.create_entity('IfcProductDefinitionShape', Representations=(body,)))


@pytest.mark.parametrize('mapped', [False, True])
def test_reference_curves_are_accounted_separately_from_failed_solids(small_ifc, tmp_path, mapped):
    path, guid = small_ifc
    model = ifcopenshell.open(str(path))
    reference = add_reference(model, model.by_guid(guid), mapped=mapped)
    model.write(str(path))
    original = path.read_bytes()
    assets = tmp_path / 'assets'
    assets.mkdir()
    result = inspect_ifc(path, assets)
    assert result['status'] == 'completed', result['diagnostics']
    assert result['reference_count'] == 1
    assert result['excluded_count'] == 0
    assert result['element_count'] == 1
    assert {item['guid'] for item in result['reference_elements']} == {reference.GlobalId}
    assert len(result['inventory']) == result['total_element_count'] == 2
    assert path.read_bytes() == original


@pytest.mark.parametrize('ifc_class,identifier', [('IfcWall', 'Annotation'), ('IfcBuildingElementProxy', 'Body')])
def test_curves_claimed_as_physical_geometry_remain_unassessed(small_ifc, ifc_class, identifier):
    path, guid = small_ifc
    model = ifcopenshell.open(str(path))
    curve = add_reference(model, model.by_guid(guid), ifc_class=ifc_class, identifier=identifier)
    model.write(str(path))
    result = inspect_ifc(path)
    assert result['status'] == 'partial'
    assert result.get('reference_count', 0) == 0
    assert result['excluded_count'] == 1
    assert any(item['guid'] == curve.GlobalId for item in result['diagnostics'])


def test_proxy_and_geometric_set_with_real_surface_are_not_filtered(small_ifc):
    path, guid = small_ifc
    model = ifcopenshell.open(str(path))
    wall = model.by_guid(guid)
    wall.Name = 'Model Lines:looks like reference'
    surface = model.create_entity('IfcPlane', Position=model.create_entity('IfcAxis2Placement3D',
                                  Location=model.create_entity('IfcCartesianPoint', Coordinates=(0., 0., 0.))))
    body = wall.Representation.Representations[0]
    proxy = model.create_entity('IfcBuildingElementProxy', GlobalId=ifcopenshell.guid.new(), Name='Model Lines',
                               ObjectPlacement=wall.ObjectPlacement, Representation=wall.Representation)
    curve = add_reference(model, wall)
    curve.Representation.Representations[0].Items[0].Elements += (surface,)
    model.write(str(path))
    result = inspect_ifc(path)
    assert {guid, proxy.GlobalId}.issubset({item['guid'] for item in result['elements']})
    assert result.get('reference_count', 0) == 0
    assert result['excluded_count'] == 1


def test_clash_inventories_original_ifc_even_when_preview_mapping_omits_a_solid(demo_sources):
    from app.clash import check_clashes
    source = demo_sources[0]
    mapping = json.loads(Path(source['mapping_path']).read_text(encoding='utf-8'))
    mapping['elements'] = []
    Path(source['mapping_path']).write_text(json.dumps(mapping), encoding='utf-8')
    source['result']['excluded_count'] += 64  # An old reader incorrectly marked reference curves as failures.
    result = check_clashes(demo_sources, options())
    assert result['status'] == 'completed', result['diagnostics']
    assert result['coverage']['missing_geometry'] == 0
    assert len(result['issues']) == 2


def test_clash_recounts_real_missing_geometry_without_trusting_preview_counts(demo_sources):
    from app.clash import check_clashes
    source = demo_sources[0]
    model = ifcopenshell.open(source['path'])
    missing = model.create_entity('IfcBeam', GlobalId=ifcopenshell.guid.new(), Name='Missing physical beam')
    reference = add_reference(model, model.by_type('IfcWall')[0], mapped=True)
    model.write(source['path'])
    source['sha256'] = hashlib.sha256(Path(source['path']).read_bytes()).hexdigest()
    mapping = json.loads(Path(source['mapping_path']).read_text(encoding='utf-8'))
    mapping['source_sha256'] = source['sha256']
    Path(source['mapping_path']).write_text(json.dumps(mapping), encoding='utf-8')
    result = check_clashes(demo_sources, options())
    assert result['status'] == 'partial', result['diagnostics']
    assert result['coverage']['missing_geometry'] == 1
    assert result['coverage']['reference_elements'] == 1
    assert any(item.get('guid') == missing.GlobalId for item in result['geometry_diagnostics'])
    assert not any(item.get('guid') == reference.GlobalId for item in result['geometry_diagnostics'])


def test_clash_retries_a_failed_native_batch_and_preserves_real_openings(demo_sources, monkeypatch):
    from app.clash import check_clashes
    monkeypatch.setattr(ifcopenshell.geom, 'iterator', lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('batch failure')))
    result = check_clashes(demo_sources, options())
    assert result['status'] == 'completed', result['diagnostics']
    assert result['coverage']['missing_geometry'] == 0
    assert result['coverage']['geometry_fallback_count'] > 0
    assert len(result['issues']) == 2


def test_automatic_reimport_upgrades_old_reader_without_overwriting_history(workspace):
    from app.demo import demo_files
    factory, _, directory = workspace
    item = demo_files()[0]
    with factory() as client:
        identifier = project(client)
        def upload():
            response = client.post('/api/inspections', files={'file': (item['name'], item['content'].encode())},
                                   data={'project_id': identifier, 'logical_source': item['name']}, headers=AUTH)
            assert response.status_code == 200, response.text
            return response.json()
        first = upload()
        path = directory / 'reports' / f"{first['id']}.json"
        old = json.loads(path.read_text(encoding='utf-8'))
        old['result'].pop('geometry_policy', None)
        path.write_text(json.dumps(old), encoding='utf-8')
        before = path.read_bytes()
        second = upload()
        assert second['id'] != first['id']
        assert second['result']['geometry_policy'] > 0
        assert upload()['id'] == second['id']
        assert path.read_bytes() == before
        assert client.get(first['report_url'], headers=AUTH).status_code == 200
        latest = client.get(f'/api/projects/{identifier}/inspections', headers=AUTH).json()
        assert latest['total'] == 1 and latest['items'][0]['id'] == second['id']


def test_submillimetre_tolerance_refines_precise_mesh_in_both_cache_and_direct_runs(demo_sources, tmp_path):
    from app.clash import check_clashes
    for cache in (None, tmp_path / 'cache'):
        result = check_clashes(demo_sources, options(tolerance_mm=.1), cache_dir=cache)
        assert result['status'] == 'completed', result['diagnostics']
        assert result['geometry_settings']['linear_deflection_m'] <= .00005
        assert len(result['issues']) == 2


def test_invalid_native_opening_does_not_make_an_uncut_host_look_complete(demo_sources, tmp_path):
    from app.clash import check_clashes
    source = demo_sources[0]
    model = ifcopenshell.open(source['path'])
    opening = model.by_type('IfcOpeningElement')[0]
    opening.Representation.Representations[0].Items[0].Depth = 0.
    host = model.by_type('IfcWall')[0]
    model.write(source['path'])
    source['sha256'] = hashlib.sha256(Path(source['path']).read_bytes()).hexdigest()
    mapping = json.loads(Path(source['mapping_path']).read_text(encoding='utf-8'))
    mapping['source_sha256'] = source['sha256']
    Path(source['mapping_path']).write_text(json.dumps(mapping), encoding='utf-8')
    imported = inspect_ifc(Path(source['path']))
    assert imported['status'] == 'partial'
    assert host.GlobalId not in {item['guid'] for item in imported['elements']}
    for cache in (None, tmp_path / 'cache'):
        result = check_clashes(demo_sources, options(), cache_dir=cache)
        assert result['status'] == 'partial', result['diagnostics']
        assert result['coverage']['missing_geometry'] >= 2
        assert {host.GlobalId, opening.GlobalId}.issubset({item.get('guid') for item in result['geometry_diagnostics']})
        assert not any(item['a']['guid'] == host.GlobalId or item['b']['guid'] == host.GlobalId for item in result['issues'])


def test_cached_clash_holds_at_most_two_source_meshes_per_tree(demo_sources, tmp_path, monkeypatch):
    from app.clash import check_clashes
    import app.clash_cache as cache
    pairs = []
    original_pair = cache.check_cached_pair
    def bounded_pair(sources, *args, **kwargs):
        assert len(sources) == 2
        pairs.append(tuple(source['id'] for source in sources))
        return original_pair(sources, *args, **kwargs)
    monkeypatch.setattr(cache, 'check_cached_pair', bounded_pair)
    ownership = {}
    for source in demo_sources:
        mapping = json.loads(Path(source['mapping_path']).read_text(encoding='utf-8'))
        ownership.update({item['guid']: source['id'] for item in mapping['elements']})
    original = ifcopenshell.geom.tree
    class BoundedTree:
        def __init__(self):
            self.inner = original()
            self.sources = set()
        def add_element(self, shape):
            self.sources.add(ownership[shape.guid])
            assert len(self.sources) <= 2, 'Release meshes after each source pair instead of retaining all IFCs'
            return self.inner.add_element(shape)
        def __getattr__(self, name):
            return getattr(self.inner, name)
    monkeypatch.setattr(ifcopenshell.geom, 'tree', BoundedTree)
    result = check_clashes(demo_sources, options(), cache_dir=tmp_path / 'cache')
    assert result['status'] == 'completed', result['diagnostics']
    assert len(result['issues']) == 2
    assert result['evaluation']['recall'] == 1.
    assert len(pairs) == len(set(pairs)) == 3
    direct_pair = check_clashes(demo_sources[:2], options(), cache_dir=tmp_path / 'cache')
    assert direct_pair['status'] == 'completed', direct_pair['diagnostics']


def test_isolated_pair_limit_keeps_findings_and_never_claims_all_pairs_complete(demo_sources, tmp_path, monkeypatch):
    import app.clash as engine
    monkeypatch.setattr(engine, 'MAX_ISSUES', 1)
    result = engine.check_clashes(demo_sources, options(), cache_dir=tmp_path / 'cache')
    assert result['status'] == 'partial' and result['verdict'] == 'incomplete'
    assert len(result['issues']) == 1
    assert {'code': 'clash_issue_limit', 'limit': 1} in result['diagnostics']


@pytest.mark.parametrize('reference_only', [False, True])
def test_empty_source_pairs_keep_inventory_and_do_not_abort_other_geometry(demo_sources, tmp_path, reference_only):
    from app.clash import check_clashes
    for index, source in enumerate(demo_sources[:2]):
        model = ifcopenshell.open(source['path'])
        products = model.by_type('IfcElement')
        if reference_only:
            owner = next(product for product in products if product.Representation)
            add_reference(model, owner)
            for product in products:
                model.remove(product)
        else:
            for product in products:
                product.Representation = None
        model.write(source['path'])
        assets = tmp_path / f'empty-{index}'
        assets.mkdir()
        source.update(result=inspect_ifc(Path(source['path']), assets), mapping_path=str(assets / 'model.json'),
                      sha256=hashlib.sha256(Path(source['path']).read_bytes()).hexdigest())
    result = check_clashes(demo_sources, options(), cache_dir=tmp_path / 'cache')
    assert result['status'] == ('completed' if reference_only else 'partial'), result['diagnostics']
    assert result['coverage']['tested_elements'] == demo_sources[2]['result']['element_count']
    assert len(result['source_inventories']) == 3
    if reference_only:
        assert result['coverage']['reference_elements'] == 2
    else:
        assert result['coverage']['missing_geometry'] > 0

