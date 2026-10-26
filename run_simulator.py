"""Run physics and the viewer with shared command state; no Flask reloader."""
# LEAP2_BOOT_SHIELD v2 -- marker checked by setup.ps1; do not remove.
import os
import signal
import socket
import sys
import threading
from threading import Thread

VIEWER_PORT = 5000


CONSOLE_COLORS = {
    'cyan': '\033[96m',
    'blue': '\033[94m',
    'purple': '\033[95m',
    'green': '\033[92m',
    'amber': '\033[93m',
    'muted': '\033[90m',
}


def _enable_console_colors():
    """Use terminal colors when supported; keep redirected boot logs plain."""
    if not sys.stdout.isatty() or 'NO_COLOR' in os.environ:
        return False
    if os.name != 'nt':
        return os.environ.get('TERM') != 'dumb'
    try:
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetStdHandle.argtypes = [wintypes.DWORD]
        kernel.GetStdHandle.restype = wintypes.HANDLE
        kernel.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        handle = kernel.GetStdHandle(-11)
        mode = wintypes.DWORD()
        if not kernel.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel.SetConsoleMode(handle, mode.value | 0x0004))
    except (AttributeError, OSError):
        return False


_console_colors_enabled = False


def _console_line(message='', color=None):
    if _console_colors_enabled and color in CONSOLE_COLORS:
        print(CONSOLE_COLORS[color] + message + '\033[0m', flush=True)
    else:
        print(message, flush=True)


def _startup_banner():
    """Text only: no image generation, redraw loop or extra startup work."""
    _console_line()
    border = '  +' + '-' * 60 + '+'
    rows = [
        ('D H R U V A   S P A C E', 'cyan'),
        ('', 'blue'),
        ('L E A P - 2   /   A D C S', 'purple'),
        ('ATTITUDE DETERMINATION + CONTROL SIMULATOR', 'cyan'),
    ]
    _console_line(border, 'blue')
    for title, color in rows:
        _console_line('  | ' + title.ljust(58) + ' |', color)
    _console_line(border, 'blue')
    _console_line('     PHYSICS  /  NAVIGATION  /  CONTROL  /  LIVE TELEMETRY', 'amber')
    _console_line()


def _ensure_java():
    """Make the venv self-sufficient: no JAVA_HOME needed in any terminal."""
    if os.environ.get('JAVA_HOME'):
        return
    try:
        import jdk4py
        home = str(jdk4py.JAVA_HOME)
        if os.path.isdir(home):
            os.environ['JAVA_HOME'] = home
            os.environ['PATH'] = (
                os.path.join(home, 'bin') + os.pathsep
                + os.environ.get('PATH', ''))
    except Exception:
        pass


def _already_running():
    """True if another sim instance is already serving the viewer port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', VIEWER_PORT)) == 0


_stop_heartbeat = threading.Event()


def _heartbeat():
    n = 0
    while not _stop_heartbeat.wait(10):
        n += 10
        _console_line(f'  [ WORKING ] Physics initialization | {n}s elapsed', 'amber')


def main():
    global _console_colors_enabled
    _console_colors_enabled = _enable_console_colors()
    _startup_banner()
    if _already_running():
        print(f'LEAP-2 sim: ALREADY RUNNING in another window '
              f'(port {VIEWER_PORT} answers).', flush=True)
        print(f'  -> open http://127.0.0.1:{VIEWER_PORT} in your browser, or',
              flush=True)
        print('     close the other sim window/terminal and run this again.',
              flush=True)
        raise SystemExit(0)
    _console_line('  [ 1 / 3 ] Preparing the runtime', 'cyan')
    _console_line('  First startup can take 1-3 minutes. Progress appears below.', 'muted')
    _console_line('  Startup is protected; Ctrl+C becomes available when ready.', 'muted')
    _ensure_java()
    try:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    except Exception:
        pass
    threading.Thread(target=_heartbeat, name='boot-heartbeat',
                     daemon=True).start()
    try:
        _console_line('  [ 2 / 3 ] Loading physics and navigation', 'purple')
        # Keep JVM/physics initialization and propagation on the main thread.
        from satellite_flight_visualisation import run_simulation, _telemetry_publisher
        from app import app, accept_telemetry_snapshot
    finally:
        _stop_heartbeat.set()
    try:
        signal.signal(signal.SIGINT, signal.SIG_DFL)
    except Exception:
        pass
    _telemetry_publisher.set_sink(accept_telemetry_snapshot)
    try:
        from waitress import serve
        server = lambda: serve(app, host='127.0.0.1', port=VIEWER_PORT,
                               threads=4)
    except ImportError:
        server = lambda: app.run(host='127.0.0.1', port=VIEWER_PORT,
                                 threaded=True, debug=False, use_reloader=False)
    _console_line('  [ 3 / 3 ] Starting the viewer and simulation', 'cyan')
    Thread(target=server, name='viewer-http', daemon=True).start()
    _console_line()
    _console_line(f'Viewer: http://127.0.0.1:{VIEWER_PORT}', 'green')
    _console_line('  Open the viewer in your browser. Ctrl+C stops the simulation.', 'muted')
    _console_line()
    try:
        run_simulation()
    except OSError as e:
        # WinError 10048: another instance already bound the firmware/SITL port
        if getattr(e, 'winerror', None) == 10048 or e.errno in (48, 98, 10048):
            print('\nAnother LEAP-2 sim instance is already running (its port '
                  'is already bound).', flush=True)
            print('Close the other sim window/terminal and run this again.',
                  flush=True)
            raise SystemExit(1)
        raise


if __name__ == '__main__':
    main()