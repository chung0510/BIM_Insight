"""Keep full IFC parsing in short-lived workers; retain only precise meshes for clashes."""
import hashlib
from contextlib import contextmanager
import errno
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

import ifcopenshell
import ifcopenshell.geom
import numpy as np

from app.inspections import stop_worker
from app.limits import MAX_ELEMENTS, MAX_REPORT_BYTES
from app.ifc_policy import IFC_GEOMETRY_POLICY


# Bump when body/opening selection, mesh validation or the cache layout changes.
CACHE_VERSION = 3


def digest(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def definition(source, settings):
    from app.clash import SOURCE_MESH_BACKEND
    if not Path(source['path']).is_file():
        raise ValueError('clash_source_missing')
    if digest(source['path']) != source['sha256']:
        raise ValueError('clash_source_hash_mismatch')
    mapping = Path(source['mapping_path'])
    if json.loads(mapping.read_text(encoding='utf-8'))['source_sha256'] != source['sha256']:
        raise ValueError('clash_source_hash_mismatch')
    if not source['result'].get('length_unit_verified'):
        raise ValueError('ifc_units_unknown')
    return {'version': CACHE_VERSION, 'geometry_policy': IFC_GEOMETRY_POLICY, 'ifcopenshell': ifcopenshell.version,
            'source_mesh_backend': SOURCE_MESH_BACKEND,
            'source_sha256': source['sha256'], 'mapping_sha256': digest(mapping),
            'linear_deflection_m': settings.get('mesher-linear-deflection'),
            'angular_deflection_rad': settings.get('mesher-angular-deflection'),
            'weld_vertices': settings.get('weld-vertices'), 'convert_back_units': settings.get('convert-back-units')}


def read_manifest(directory, expected):
    try:
        path = directory / 'manifest.json'
        if path.stat().st_size > MAX_REPORT_BYTES:
            return None
        manifest = json.loads(path.read_text(encoding='utf-8'))
        if manifest['definition'] != expected or len(manifest['elements']) > MAX_ELEMENTS:
            return None
        for name in ('geometry.h5', 'objects.ifc'):
            if digest(directory / name) != manifest['files'][name]:
                return None
        return manifest
    except PermissionError:
        raise ValueError('clash_cache_permission_denied') from None
    except (OSError, ValueError, KeyError, TypeError):
        return None


@contextmanager
def cache_lock(path):
    with Path(path).open('a+b') as handle:
        if os.name == 'nt':
            import msvcrt
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            while True:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as error:
                    if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                        raise
                    time.sleep(.1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == 'nt':
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def build_source_cache(source, destination, expected, threads, update, work_dir, remaining):
    with cache_lock(destination.with_suffix('.lock')):
        build_locked_source_cache(source, destination, expected, threads, update, work_dir, remaining)


def build_locked_source_cache(source, destination, expected, threads, update, work_dir, remaining):
    if read_manifest(destination, expected) is not None:
        return
    with tempfile.TemporaryDirectory(prefix='geometry-', dir=work_dir) as temporary:
        work = Path(temporary)
        output = work / 'cache'
        output.mkdir()
        config = work / 'config.json'
        config.write_text(json.dumps({'source': source, 'definition': expected, 'threads': threads,
                                     'remaining': remaining}, ensure_ascii=False), encoding='utf-8')
        command = [sys.executable]
        if not getattr(sys, 'frozen', False):
            command += ['-m', 'app']
        command += ['--clash-geometry-worker', str(config), str(output), '--parent-pid', str(os.getpid())]
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                                   env={**os.environ, 'PYTHONPATH': os.pathsep.join([str(Path(__file__).resolve().parents[1]), os.environ.get('PYTHONPATH', '')])})
        last = None
        try:
            while process.poll() is None:
                try:
                    path = work / 'progress.json'
                    if path.stat().st_size <= 8192:
                        current = json.loads(path.read_text(encoding='utf-8'))
                        if current != last:
                            update(current['phase'], **{key: value for key, value in current.items() if key != 'phase'})
                            last = current
                except (OSError, ValueError, KeyError):
                    pass
                time.sleep(.1)
        finally:
            stop_worker(process)
        error = output / 'error.json'
        if error.is_file():
            raise ValueError(json.loads(error.read_text(encoding='utf-8'))['code'])
        if process.returncode or read_manifest(output, expected) is None:
            raise ValueError('clash_geometry_failed')
        if read_manifest(destination, expected) is not None:
            return
        if destination.exists():
            # Only replace this generated hash directory, never a source or project directory.
            if destination.is_symlink() or destination.resolve().parent != destination.parent.resolve():
                raise ValueError('clash_geometry_failed')
            shutil.rmtree(destination)
        try:
            os.replace(output, destination)
        except OSError:
            if read_manifest(destination, expected) is None:
                raise


def write_source_cache(config, output):
    from app.clash import load_source_geometry, precise_settings

    inputs = json.loads(Path(config).read_text(encoding='utf-8'))
    source, output = inputs['source'], Path(output)
    settings = precise_settings(inputs['definition']['linear_deflection_m'])
    last_write = 0.
    def update(phase, **values):
        nonlocal last_write
        now = time.monotonic()
        if now - last_write >= 1 or values.get('done') == values.get('total'):
            Path(config).with_name('progress.json').write_text(json.dumps({'phase': phase, **values}), encoding='utf-8')
            last_write = now
    writer = None
    serializer_settings = ifcopenshell.geom.serializer_settings()
    try:
        if definition(source, settings) != inputs['definition']:
            raise ValueError('clash_source_hash_mismatch')
        writer = ifcopenshell.geom.serializers.hdf5(str(output / 'geometry.h5'), settings, serializer_settings)
        writer.writeHeader()
        elements = []
        def consume(shape, product, record):
            writer.write(shape)
            elements.append({**record, 'closed': bool(record['closed']), 'min': record['min'].tolist(), 'max': record['max'].tolist(),
                             'step_id': product.id(), 'representation_id': shape.geometry.id.split('-', 1)[0]})
        model, group, counts, details = load_source_geometry(source, settings, inputs['threads'], consume, update, inputs['remaining'])
        writer.finalize()
        del writer
        writer = None
        objects = ifcopenshell.file(schema=model.schema_identifier)
        for product in group:
            objects.create_entity(product.is_a(), id=product.id(), GlobalId=product.GlobalId, Name=product.Name)
        for style in model.by_type('IfcSurfaceStyle'):
            objects.create_entity('IfcSurfaceStyle', id=style.id(), Side='BOTH')
        objects.write(str(output / 'objects.ifc'))
        manifest = {'definition': inputs['definition'], 'counts': counts, 'details': details, 'elements': elements,
                    'files': {name: digest(output / name) for name in ('geometry.h5', 'objects.ifc')}}
        (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
        code = 'clash_cache_permission_denied' if isinstance(error, PermissionError) else str(error) if str(error).startswith(('clash_', 'ifc_', 'processing_')) else 'clash_geometry_failed'
        (output / 'error.json').write_text(json.dumps({'code': code}), encoding='utf-8')
    finally:
        del writer


def prepare_cached_geometry(source, directory, work_dir, settings, threads, update, remaining):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    expected = definition(source, settings)
    key = hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest()
    destination = directory / key
    manifest = read_manifest(destination, expected)
    if manifest is None:
        build_source_cache(source, destination, expected, threads, update, work_dir or directory, remaining)
        manifest = read_manifest(destination, expected)
    if manifest is None:
        raise ValueError('clash_geometry_failed')
    counts = manifest['counts']
    if counts['tested_elements'] + counts['missing_geometry'] > remaining:
        raise ValueError('clash_scope_limit')
    return destination, manifest


def load_cached_geometry(source, directory, work_dir, settings, threads, consume, update, remaining):
    destination, manifest = prepare_cached_geometry(source, directory, work_dir, settings, threads, update, remaining)
    counts = manifest['counts']
    model = ifcopenshell.open(str(destination / 'objects.ifc'))
    group = []
    elements = manifest['elements']
    serializer_settings = ifcopenshell.geom.serializer_settings()
    update('loading_geometry', done=0, total=len(elements))
    for item in elements:
        product = model.by_id(item['step_id'])
        # A fresh reader avoids HDF's representation-id reuse across different opening cuts.
        reader = ifcopenshell.geom.serializers.hdf5(str(destination / 'geometry.h5'), settings, serializer_settings, True)
        shape = reader.read(model.wrapped_data, item['guid'], item['representation_id'], reader.READ_TRIANGULATION)
        if shape is None or shape.guid != product.GlobalId:
            raise ValueError('clash_geometry_failed')
        # Keep native ownership: forcing deletion corrupts SWIG handles in IfcOpenShell 0.8.5.
        record = {key: value for key, value in item.items() if key not in {'step_id', 'representation_id'}}
        record.update(source_id=source['id'], source_name=source['name'], min=np.array(item['min']), max=np.array(item['max']))
        consume(shape, product, record)
        group.append(product)
        del shape, reader
        update('loading_geometry', done=len(group), total=len(elements))
    return model, group, counts, manifest['details']


def check_cached_pair(sources, parameters, directory, work_dir, update):
    # Isolate native HDF/BVH allocations so Windows reclaims them after each source pair.
    if len(sources) != 2:
        raise ValueError('clash_scope_limit')
    with tempfile.TemporaryDirectory(prefix='pair-', dir=work_dir or directory) as temporary:
        work = Path(temporary)
        config, output = work / 'config.json', work / 'result.json'
        config.write_text(json.dumps({'sources': sources, 'parameters': parameters,
                                      'geometry_cache': str(Path(directory).resolve())}, ensure_ascii=False), encoding='utf-8')
        command = [sys.executable]
        if not getattr(sys, 'frozen', False):
            command += ['-m', 'app']
        command += ['--clash-worker', str(config), str(output), '--parent-pid', str(os.getpid())]
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                                   env={**os.environ, 'PYTHONPATH': os.pathsep.join([str(Path(__file__).resolve().parents[1]), os.environ.get('PYTHONPATH', '')])})
        last = None
        try:
            while process.poll() is None:
                try:
                    path = work / 'progress.json'
                    if path.stat().st_size <= 8192:
                        current = json.loads(path.read_text(encoding='utf-8'))
                        if current != last:
                            update(current)
                            last = current
                except (OSError, ValueError):
                    pass
                time.sleep(.1)
        finally:
            stop_worker(process)
        if process.returncode or not output.is_file() or output.stat().st_size > MAX_REPORT_BYTES:
            raise ValueError('clash_geometry_failed')
        result = json.loads(output.read_text(encoding='utf-8'))
        if result.get('status') == 'failed':
            raise ValueError(next(iter(result.get('diagnostics', [])), {}).get('code', 'clash_geometry_failed'))
        return result
