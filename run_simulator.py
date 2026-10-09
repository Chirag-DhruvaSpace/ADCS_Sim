"""Run physics and the viewer with shared command state; no Flask reloader."""
# LEAP2_BOOT_SHIELD v1 -- marker checked by setup.ps1; do not remove.
import os
import signal
import threading
from threading import Thread


def _ensure_java():
    """Make the venv self-sufficient: no JAVA_HOME needed in any terminal.

    The JDK lives INSIDE the venv (jdk4py). If this terminal forgot to set
    JAVA_HOME, resolve it here so jpype finds jvm.dll. This removes the
    setup-vs-manual difference: the program no longer depends on the
    environment it was launched from.
    """
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


_stop_heartbeat = threading.Event()


def _heartbeat():
    n = 0
    while not _stop_heartbeat.wait(10):
        n += 10
        print(f'  ... still starting up ({n}s) - normal, do not close this window',
              flush=True)


def main():
    print('LEAP-2 sim booting: importing the physics stack (heartbeat below; '
          'can take 1-3 min on corporate laptops). Ctrl+C is ignored until '
          'the sim is up.', flush=True)
    _ensure_java()
    try:
        signal.signal(signal.SIGINT, signal.SIG_IGN)   # immune while booting
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
        signal.signal(signal.SIGINT, signal.SIG_DFL)   # Ctrl+C works again
    except Exception:
        pass
    _telemetry_publisher.set_sink(accept_telemetry_snapshot)
    try:
        from waitress import serve
        server = lambda: serve(app, host='127.0.0.1', port=5000, threads=4)
    except ImportError:
        server = lambda: app.run(host='127.0.0.1', port=5000, threaded=True,
                                 debug=False, use_reloader=False)
    Thread(target=server, name='viewer-http', daemon=True).start()
    print('Viewer: http://127.0.0.1:5000', flush=True)
    run_simulation()


if __name__ == '__main__':
    main()