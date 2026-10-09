"""Run physics and the viewer with shared command state; no Flask reloader."""
from threading import Thread


def main():
    # Keep JVM/physics initialization and propagation on the main thread.
    from satellite_flight_visualisation import run_simulation, _telemetry_publisher
    from app import app, accept_telemetry_snapshot
    _telemetry_publisher.set_sink(accept_telemetry_snapshot)
    try:
        from waitress import serve
        server = lambda: serve(app, host='127.0.0.1', port=5000, threads=4)
    except ImportError:
        server = lambda: app.run(host='127.0.0.1', port=5000, threaded=True,
                                 debug=False, use_reloader=False)
    Thread(target=server, name='viewer-http', daemon=True).start()
    print('Viewer: http://127.0.0.1:5000')
    run_simulation()


if __name__ == '__main__':
    main()
