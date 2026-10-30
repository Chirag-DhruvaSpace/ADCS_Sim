"""Optional JVM acceleration; preserves the NumPy ray-test fallback.

Compiles the bundled generic source once per JDK/source version, before the
packet clock starts. No spacecraft geometry is embedded in the helper.
"""
from functools import lru_cache
from pathlib import Path
import hashlib
import os
import subprocess
import shutil
import tempfile
import warnings
import numpy as np


@lru_cache(maxsize=1)
def _visibility_class():
    import jpype
    if not jpype.isJVMStarted():
        return None
    source = Path(__file__).with_name('FacetVisibility.java')
    java_home = Path(str(jpype.JClass('java.lang.System').getProperty('java.home')))
    compiler = java_home / 'bin' / ('javac.exe' if os.name == 'nt' else 'javac')
    if not compiler.is_file():
        found = shutil.which('javac')
        if found is None:
            return None
        compiler = Path(found)
    release = str(jpype.JClass('java.lang.System').getProperty('java.specification.version'))
    digest = hashlib.sha256(source.read_bytes()+str(compiler).encode()+release.encode()+b'atomic-v2').hexdigest()[:20]
    cache = source.parents[2] / '.cache' / 'facet-visibility' / digest
    compiled = cache / 'leap' / 'physics' / 'FacetVisibility.class'
    if not compiled.is_file():
        cache.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=cache) as staging:
            result = subprocess.run([str(compiler), '-source', release, '-target', release,
                '-d', staging, str(source)], capture_output=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            # The helper uses only java.lang and primitive arrays (no recent
            # APIs); source/target also works with compact runtime JREs.
            if result.returncode:
                return None
            compiled.parent.mkdir(parents=True, exist_ok=True)
            os.replace(Path(staging)/'leap'/'physics'/'FacetVisibility.class', compiled)
    # Use an explicit loader: the live launcher may already have initialized
    # JPype's application loader before this generated directory exists.
    File = jpype.JClass('java.io.File')
    URL = jpype.JClass('java.net.URL')
    URLClassLoader = jpype.JClass('java.net.URLClassLoader')
    parent = jpype.JClass('java.lang.ClassLoader').getSystemClassLoader()
    loader = URLClassLoader.newInstance(jpype.JArray(URL)([File(str(cache)).toURI().toURL()]), parent)
    return jpype.JClass('leap.physics.FacetVisibility', loader=loader)


def make_visibility(positions, lo, hi):
    try:
        import jpype
        if not jpype.isJVMStarted():
            return None
        cls = _visibility_class()
        if cls is None:
            return None
        doubles = jpype.JArray(jpype.JDouble, 2)
        instance = cls(doubles(positions), doubles(lo), doubles(hi))
        def visible(direction, active):
            mask = np.ones(len(positions), dtype=bool) if active is None else active
            return np.asarray(instance.visible(direction, mask), dtype=bool)
        return visible
    except ImportError:
        return None
    except (OSError, RuntimeError, TypeError, subprocess.SubprocessError, jpype.JException) as error:
        warnings.warn(f'Facet acceleration unavailable ({error}); using NumPy shadow checks.',
                      RuntimeWarning, stacklevel=2)
        return None
