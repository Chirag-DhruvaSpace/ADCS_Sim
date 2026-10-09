"""Run physics and the viewer with shared command state; no Flask reloader."""
# LEAP2_BOOT_SHIELD v2 -- marker checked by setup.ps1; do not remove.
import os
import signal
import socket
import threading
from threading import Thread

VIEWER_PORT = 5000


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
        print(f'  ... still starting up ({n}s) - normal, wait for the '
              f'"Viewer:" line', flush=True)


def main():
    if _already_running():
        print(f'LEAP-2 sim: ALREADY RUNNING in another window '
              f'(port {VIEWER_PORT} answers).', flush=True)
        print(f'  -> open http://127.0.0.1:{VIEWER_PORT} in your browser, or',
              flush=True)
        print('     close the other sim window/terminal and run this again.',
              flush=True)
        raise SystemExit(0)
    print('LEAP-2 sim booting: importing the physics stack (heartbeat below; '
          'can take 1-3 min on corporate laptops). Ctrl+C is ignored until '
          'the sim is up.', flush=True)
    _ensure_java()
    try:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    except Exception:
        pass
    threading.Thread(target=_heartbeat, name='boot-heartbeat',
                     daemon=True).start()
    try:
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
    Thread(target=server, name='viewer-http', daemon=True).start()
    print(f'Viewer: http://127.0.0.1:{VIEWER_PORT}', flush=True)
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