"""Build the ADS SITL executable with the installed MinGW gcc compiler."""
import argparse
from pathlib import Path
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor


def build(output, *, shared=False, extra_sources=(), main_source=None):
    sim = Path(__file__).resolve().parents[2]
    ads = sim.parents[1] / 'Firmware' / 'ADS'
    gcc = shutil.which('gcc')
    if not gcc:
        raise RuntimeError('MinGW gcc is required (for example C:/msys64/ucrt64/bin/gcc.exe)')
    # Hardware-only drivers are replaced by the existing SITL adapters.
    sources = [str(p) for p in sorted((ads / 'Src').rglob('*.c'))
               if p.name not in {'my_flash.c', 'fdir.c'} and (p.parent.name != 'sensor'
               or p.name in {'sun_vector_body.c', 'star_tracker_absquat.c'})]
    if main_source is not None:
        sources = [str(main_source) if p == str(ads / 'Src/main.c') else p for p in sources]
    includes = [ads / 'Inc', ads / 'Inc' / 'architecture']
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [gcc, '-std=gnu11', '-O2', '-fcommon', '-D_WIN32_WINNT=0x0600',
               '-include', str(ads / 'sitl_force_include.h')]
    command += [f'-I{p}' for p in includes]
    objects_dir = sim / '.cache/yaw_steering/objects'
    objects_dir.mkdir(parents=True, exist_ok=True)
    header_time = max(p.stat().st_mtime for p in (ads / 'Inc').rglob('*.h'))
    def compile_source(source):
        source = Path(source)
        name = '_'.join(source.relative_to(ads).parts) if source.is_relative_to(ads) else source.name
        obj = objects_dir / (name + '.o')
        if obj.exists() and obj.stat().st_mtime > max(source.stat().st_mtime, header_time, Path(__file__).stat().st_mtime):
            return str(obj), '', 0
        result = subprocess.run(command + ['-c', str(source), '-o', str(obj)], capture_output=True, text=True)
        return str(obj), result.stdout + result.stderr, result.returncode
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(compile_source, sources + list(extra_sources)))
    logs = ''.join(result[1] for result in results)
    if not any(result[2] for result in results):
        link = [gcc] + [result[0] for result in results]
        if shared:
            link += ['-shared', '-Wl,--export-all-symbols']
        result = subprocess.run(link + ['-o', str(output), '-lws2_32', '-lm'], capture_output=True, text=True)
        logs += result.stdout + result.stderr
        failed = result.returncode
    else:
        failed = True
    output.with_suffix('.build.log').write_text(logs, encoding='utf-8')
    if failed:
        print('\n'.join(line for line in logs.splitlines() if 'error:' in line or 'undefined reference' in line))
        raise RuntimeError(f'Build failed; see {output.with_suffix(".build.log")}')
    print(f'Built {output}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='.cache/yaw_steering/sitl_ads.exe')
    build(parser.parse_args().output)
