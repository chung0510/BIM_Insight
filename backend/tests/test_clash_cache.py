import hashlib
from pathlib import Path
import os
import subprocess
import sys
import time

import ifcopenshell
import ifcopenshell.api.geometry
import ifcopenshell.util.shape
import pytest

from app.ifc import inspect_ifc
from test_clash import demo_sources, options, add_missing_geometry


def findings(report):
    return {(item['a']['guid'], item['b']['guid'], item['kind']): item['distance_m'] for item in report['issues']}


def test_unreadable_cache_reports_permissions_without_rebuilding_or_deleting_it(demo_sources, tmp_path, monkeypatch):
    import app.clash_cache as cache
    from app.clash import check_clashes
    directory = tmp_path / 'cache'
    assert check_clashes(demo_sources[:1], options(), cache_dir=directory)['status'] == 'completed'
    manifest = next(directory.glob('*/manifest.json'))
    original = manifest.read_bytes()
    original_open = Path.open
    def denied(path, *args, **kwargs):
        if path == manifest:
            raise PermissionError('Cache belongs to another Windows account')
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', denied)
    def never_rebuild(*args, **kwargs):
        pytest.fail('Permission failure must be reported before expensive native conversion')
    monkeypatch.setattr(cache, 'build_source_cache', never_rebuild)
    result = check_clashes(demo_sources[:1], options(), cache_dir=directory)
    assert result['status'] == 'failed'
    assert result['diagnostics'] == [{'code': 'clash_cache_permission_denied'}]
    with original_open(manifest, 'rb') as handle:
        assert handle.read() == original


def test_cache_writer_permission_error_keeps_specific_diagnostic(demo_sources, tmp_path, monkeypatch):
    import json
    import app.clash_cache as cache
    from app.clash import precise_settings
    source = demo_sources[0]
    output = tmp_path / 'output'
    output.mkdir()
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'source':source, 'definition':cache.definition(source,precise_settings()),
                                  'threads':1, 'remaining':100000}),encoding='utf-8')
    def denied(*args, **kwargs):
        raise PermissionError('Cannot write geometry cache')
    monkeypatch.setattr(ifcopenshell.geom.serializers, 'hdf5', denied)
    cache.write_source_cache(config,output)
    assert json.loads((output/'error.json').read_text(encoding='utf-8'))['code'] == 'clash_cache_permission_denied'


def test_cached_clash_keeps_geometry_verdict_and_reuses_completed_sources(demo_sources, tmp_path, monkeypatch):
    import app.clash as engine
    import app.clash_cache as cache

    baseline = engine.check_clashes(demo_sources, options(mode='clearance'))
    directory = tmp_path / 'geometry-cache'
    cold = engine.check_clashes(demo_sources, options(mode='clearance'), cache_dir=directory)
    assert cold['status'] == baseline['status'], cold['diagnostics']
    assert cold['coverage'] == baseline['coverage']
    assert findings(cold) == pytest.approx(findings(baseline), abs=1e-9)
    assert cold['evaluation'] == baseline['evaluation']

    def unexpected_build(*args, **kwargs):
        raise AssertionError('A completed precise mesh must not be rebuilt on a second run')
    monkeypatch.setattr(cache, 'build_source_cache', unexpected_build)
    original_open = ifcopenshell.open
    def lightweight_open(path, *args, **kwargs):
        assert Path(path).name == 'objects.ifc', 'Parent must not retain full source IFCs'
        model = original_open(path, *args, **kwargs)
        assert all(item.Representation is None for item in model.by_type('IfcElement'))
        return model
    monkeypatch.setattr(ifcopenshell, 'open', lightweight_open)
    events = []
    warm = engine.check_clashes(demo_sources, options(mode='clearance'), cache_dir=directory, progress=events.append)
    assert warm['coverage'] == baseline['coverage']
    assert findings(warm) == pytest.approx(findings(baseline), abs=1e-9)
    assert any(event['phase'] == 'loading_geometry' for event in events)


def test_cached_mesh_corruption_is_rebuilt_and_changed_source_is_rejected(demo_sources, tmp_path):
    from app.clash import check_clashes

    directory = tmp_path / 'geometry-cache'
    before = check_clashes(demo_sources, options(), cache_dir=directory)
    assert before['status'] == 'completed'
    mesh = next(directory.glob('*/geometry.h5'))
    mesh.write_bytes(b'corrupt cache')
    rebuilt = check_clashes(demo_sources, options(), cache_dir=directory)
    assert rebuilt['status'] == 'completed'
    assert findings(rebuilt) == findings(before)
    Path(demo_sources[0]['path']).write_bytes(b'changed original IFC')
    rejected = check_clashes(demo_sources, options(), cache_dir=directory)
    assert rejected['status'] == 'failed'
    assert rejected['diagnostics'][-1]['code'] == 'clash_source_hash_mismatch'


def test_shared_body_with_different_openings_survives_mesh_cache(demo_sources, tmp_path):
    from app.clash import check_clashes

    source = demo_sources[0]
    model = ifcopenshell.open(source['path'])
    wall = model.by_type('IfcWall')[0]
    model.create_entity('IfcWall', GlobalId=ifcopenshell.guid.new(), Name='Same body without opening',
                        ObjectPlacement=wall.ObjectPlacement, Representation=wall.Representation)
    model.write(source['path'])
    assets = tmp_path / 'changed-assets'
    assets.mkdir()
    source.update(result=inspect_ifc(Path(source['path']), assets), mapping_path=str(assets / 'model.json'),
                  sha256=hashlib.sha256(Path(source['path']).read_bytes()).hexdigest())
    baseline = check_clashes(demo_sources, options(mode='clearance'))
    cached = check_clashes(demo_sources, options(mode='clearance'), cache_dir=tmp_path / 'geometry-cache')
    assert baseline['status'] == cached['status'] == 'completed'
    assert cached['coverage'] == baseline['coverage']
    assert findings(cached) == pytest.approx(findings(baseline), abs=1e-9)


def test_cached_coverage_keeps_missing_geometry_and_element_limits(demo_sources, tmp_path, monkeypatch):
    import app.clash as engine

    add_missing_geometry(demo_sources[0], count=2)
    directory = tmp_path / 'geometry-cache'
    result = engine.check_clashes(demo_sources, options(), cache_dir=directory)
    assert result['status'] == 'partial'
    assert result['coverage']['missing_geometry'] == 2
    monkeypatch.setattr(engine, 'MAX_ELEMENTS', 1)
    limited = engine.check_clashes(demo_sources, options(), cache_dir=directory)
    assert limited['status'] == 'failed'
    assert limited['diagnostics'][-1]['code'] == 'clash_scope_limit'


def test_concurrent_cache_winner_is_reused_without_deleting_its_files(demo_sources, tmp_path, monkeypatch):
    import app.clash_cache as cache
    from app.clash import check_clashes, precise_settings

    directory = tmp_path / 'geometry-cache'
    result = check_clashes(demo_sources[:1], options(), cache_dir=directory)
    assert result['status'] == 'completed'
    destination = next(path for path in directory.iterdir() if path.is_dir())
    expected = cache.definition(demo_sources[0], precise_settings())
    original = (destination / 'geometry.h5').stat().st_mtime_ns
    remove = cache.shutil.rmtree
    read_manifest = cache.read_manifest
    reads = 0
    def concurrent_winner(path, settings):
        nonlocal reads
        if Path(path) == destination:
            reads += 1
            if reads == 1:
                return None
        return read_manifest(path, settings)
    def protect_winner(path, *args, **kwargs):
        assert Path(path).resolve() != destination.resolve(), 'A completed concurrent cache must stay available to readers'
        return remove(path, *args, **kwargs)
    monkeypatch.setattr(cache.shutil, 'rmtree', protect_winner)
    monkeypatch.setattr(cache, 'read_manifest', concurrent_winner)
    cache.build_source_cache(demo_sources[0], destination, expected, 1, lambda *args, **kwargs: None, tmp_path, 100_000)
    assert reads >= 2
    assert (destination / 'geometry.h5').stat().st_mtime_ns == original


def test_cache_publication_lock_serializes_different_processes(tmp_path):
    from app.clash_cache import cache_lock

    lock = tmp_path / 'geometry.lock'
    ready, acquired = tmp_path / 'ready', tmp_path / 'acquired'
    code = 'from pathlib import Path\nimport sys\nfrom app.clash_cache import cache_lock\nPath(sys.argv[2]).touch()\nwith cache_lock(Path(sys.argv[1])):\n Path(sys.argv[3]).touch()\n'
    process = None
    try:
        with cache_lock(lock):
            process = subprocess.Popen([sys.executable, '-c', code, str(lock), str(ready), str(acquired)],
                                       env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1])},
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            deadline = time.monotonic() + 5
            while not ready.is_file() and time.monotonic() < deadline:
                time.sleep(.02)
            assert ready.is_file()
            time.sleep(.15)
            assert not acquired.exists(), 'A second process must wait before validating, replacing or publishing the same cache'
        assert process.wait(timeout=5) == 0
        assert acquired.is_file()
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_geometry_iterator_releases_batches_without_omitting_elements(demo_sources, tmp_path, monkeypatch):
    from app.clash import check_clashes

    source = demo_sources[0]
    model = ifcopenshell.open(source['path'])
    wall = model.by_type('IfcWall')[0]
    for index in range(150):
        model.create_entity('IfcWall', GlobalId=ifcopenshell.guid.new(), Name=f'Batch wall {index}',
                            ObjectPlacement=wall.ObjectPlacement, Representation=wall.Representation)
    model.write(source['path'])
    assets = tmp_path / 'batched-assets'
    assets.mkdir()
    source.update(result=inspect_ifc(Path(source['path']), assets), mapping_path=str(assets / 'model.json'),
                  sha256=hashlib.sha256(Path(source['path']).read_bytes()).hexdigest())
    original = ifcopenshell.geom.iterator
    batches = []
    def bounded(settings, model, threads, **kwargs):
        batches.append(len(kwargs['include']))
        assert len(kwargs['include']) <= 128
        return original(settings, model, threads, **kwargs)
    monkeypatch.setattr(ifcopenshell.geom, 'iterator', bounded)
    result = check_clashes([source], options())
    assert result['status'] == 'completed'
    assert result['coverage']['tested_elements'] == 151
    assert batches == [128, 23]


def test_all_source_conversion_finishes_before_loading_any_clash_mesh(demo_sources, tmp_path, monkeypatch):
    import app.clash_cache as cache
    from app.clash import check_clashes

    events = []
    build = cache.build_source_cache
    def converted(source, *args, **kwargs):
        events.append(('build', source['id']))
        return build(source, *args, **kwargs)
    monkeypatch.setattr(cache, 'build_source_cache', converted)
    original_pair = cache.check_cached_pair
    def compared(sources, *args, **kwargs):
        events.append(('load', sources[0]['id']))
        return original_pair(sources, *args, **kwargs)
    monkeypatch.setattr(cache, 'check_cached_pair', compared)
    result = check_clashes(demo_sources, options(), cache_dir=tmp_path / 'geometry-cache')
    assert result['status'] == 'completed'
    first_load = next(index for index, event in enumerate(events) if event[0] == 'load')
    assert events[:first_load] == [('build', source['id']) for source in demo_sources]


@pytest.mark.parametrize('keep_opening', [False, True])
def test_explicit_mesh_fast_path_preserves_baked_and_boolean_openings(demo_sources, tmp_path, monkeypatch, keep_opening):
    import app.clash as engine

    baseline = engine.check_clashes(demo_sources, options(mode='clearance'))
    source = demo_sources[0]
    model = ifcopenshell.open(source['path'])
    wall = model.by_type('IfcWall')[0]
    settings = engine.precise_settings()
    if keep_opening:
        settings.set('disable-opening-subtractions', True)
    shape = ifcopenshell.geom.create_shape(settings, wall)
    vertices = ifcopenshell.util.shape.get_vertices(shape.geometry)
    faces = ifcopenshell.util.shape.get_faces(shape.geometry)
    mesh = ifcopenshell.api.geometry.add_mesh_representation(model, context=wall.Representation.Representations[0].ContextOfItems,
                                                            vertices=[vertices.tolist()], faces=[faces.tolist()])
    mapped = ifcopenshell.api.geometry.map_representation(model, representation=mesh)
    wall.Representation.Representations = (mapped,)
    if not keep_opening:
        for relation in list(wall.HasOpenings):
            model.remove(relation)
    assert engine.source_mesh_body(wall) is (not keep_opening)
    model.write(source['path'])
    assets = tmp_path / 'tessellated-assets'
    assets.mkdir()
    source.update(result=inspect_ifc(Path(source['path']), assets), mapping_path=str(assets / 'model.json'),
                  sha256=hashlib.sha256(Path(source['path']).read_bytes()).hexdigest())
    original = ifcopenshell.geom.iterator
    backends = []
    def measured(settings, model, threads, **kwargs):
        backends.append(kwargs.get('geometry_library', 'opencascade'))
        return original(settings, model, threads, **kwargs)
    monkeypatch.setattr(ifcopenshell.geom, 'iterator', measured)
    result = engine.check_clashes(demo_sources, options(mode='clearance'))
    assert result['status'] == 'completed', result
    assert findings(result) == pytest.approx(findings(baseline), abs=1e-9)
    assert ('hybrid-cgal-simple-opencascade' in backends) is (not keep_opening)
    assert 'opencascade' in backends


@pytest.mark.parametrize('addition', [False, True])
def test_mesh_fast_path_rejects_parametric_curves_and_inherited_features(demo_sources, addition):
    import app.clash as engine

    model = ifcopenshell.open(demo_sources[2]['path'])
    pipe = model.by_type('IfcPipeSegment')[0]
    assert not engine.source_mesh_body(pipe)
    mesh = ifcopenshell.api.geometry.add_mesh_representation(model, context=pipe.Representation.Representations[0].ContextOfItems,
                                                            vertices=[[(0.,0.,0.),(1.,0.,0.),(0.,1.,0.)]], faces=[[(0,1,2)]])
    pipe.Representation.Representations = (mesh,)
    assert engine.source_mesh_body(pipe)
    parent = model.create_entity('IfcWall', GlobalId=ifcopenshell.guid.new())
    if addition:
        feature = model.create_entity('IfcProjectionElement', GlobalId=ifcopenshell.guid.new())
        model.create_entity('IfcRelProjectsElement', GlobalId=ifcopenshell.guid.new(), RelatingElement=parent, RelatedFeatureElement=feature)
    else:
        opening = model.create_entity('IfcOpeningElement', GlobalId=ifcopenshell.guid.new())
        model.create_entity('IfcRelVoidsElement', GlobalId=ifcopenshell.guid.new(), RelatingBuildingElement=parent, RelatedOpeningElement=opening)
    model.create_entity('IfcRelNests', GlobalId=ifcopenshell.guid.new(), RelatingObject=parent, RelatedObjects=(pipe,))
    assert not engine.source_mesh_body(pipe)


def test_polygonal_mesh_keeps_inner_face_hole_in_both_backends(demo_sources):
    import numpy as np
    from app.clash import SOURCE_MESH_BACKEND, precise_settings, source_mesh_body

    model = ifcopenshell.open(demo_sources[0]['path'])
    wall = model.by_type('IfcWall')[0]
    context = wall.Representation.Representations[0].ContextOfItems
    points = model.create_entity('IfcCartesianPointList3D', CoordList=[(0.,0.,0.),(4000.,0.,0.),(4000.,4000.,0.),(0.,4000.,0.),
                                                                            (1000.,1000.,0.),(1000.,3000.,0.),(3000.,3000.,0.),(3000.,1000.,0.)])
    face = model.create_entity('IfcIndexedPolygonalFaceWithVoids', CoordIndex=(1,2,3,4), InnerCoordIndices=((5,6,7,8),))
    tessellation = model.create_entity('IfcPolygonalFaceSet', Coordinates=points, Closed=False, Faces=(face,))
    body = model.create_entity('IfcShapeRepresentation', ContextOfItems=context, RepresentationIdentifier='Body',
                               RepresentationType='Tessellation', Items=(tessellation,))
    wall.Representation.Representations = (body,)
    for relation in list(wall.HasOpenings):
        model.remove(relation)
    assert source_mesh_body(wall)
    for backend in (SOURCE_MESH_BACKEND, 'opencascade'):
        shape = ifcopenshell.geom.create_shape(precise_settings(), wall, geometry_library=backend)
        vertices = ifcopenshell.util.shape.get_shape_vertices(shape, shape.geometry)
        faces = ifcopenshell.util.shape.get_faces(shape.geometry)
        triangles = vertices[faces]
        area = np.linalg.norm(np.cross(triangles[:,1]-triangles[:,0], triangles[:,2]-triangles[:,0]), axis=1).sum()/2
        assert area == pytest.approx(12., abs=1e-9)
