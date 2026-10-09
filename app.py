# made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag
import mimetypes
from pathlib import Path
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
from flask import Flask, request, jsonify, redirect, Response, send_from_directory
from threading import Lock
import gzip
import hashlib
import control_states as cs 
import store 
import numpy as np 

app = Flask(__name__, static_folder=None)


@app.route('/api/imu/mounts', methods=['GET', 'POST'])
def imu_mount_configuration():
    from imu_mount_settings import get_mounts, request_mount
    if request.method == 'GET':
        return jsonify(get_mounts())
    try:
        result = request_mount(request.get_json(silent=True))
    except (ValueError, TypeError) as error:
        return jsonify(error=str(error)), 400
    return jsonify(mounts=result, status='Applies at next simulation tick; sensor calibration restarts.')

@app.route('/api/imu/defaults', methods=['POST'])
def imu_save_defaults():
    from imu_mount_settings import save_mount_defaults
    try:
        save_mount_defaults()
    except (ValueError, OSError) as error:
        return jsonify(error=str(error)), 400
    return jsonify(status='Mounts saved to satellite_parameters.yaml for future runs.')

# This will store the LATEST received telemetry point
latest_telemetry = {}
_telemetry_cache_lock = Lock()
_telemetry_cache = (None, None, None, None)


def accept_telemetry_snapshot(snapshot):
    """Publish an owned, immutable-by-convention snapshot without HTTP/JSON."""
    global latest_telemetry
    latest_telemetry = snapshot

# 1. POST Endpoint: Receives data from the propagator script (No Change)
@app.route('/update_telemetry', methods=['POST'])
def receive_telemetry():
    if request.is_json:
        accept_telemetry_snapshot(request.get_json())
        #print(f"📡 Received update for {latest_telemetry.get('timestamp')}")
        return jsonify(success=True, pointing_command=cs.get_pointing_command()), 200
    return jsonify({"success": False}), 400

# 2. API GET Endpoint: Serves the latest data to the HTML's JavaScript (No Change)
@app.route('/api/latest', methods=['GET'])
def get_latest_telemetry():
    # Returns the stored data as JSON
    global _telemetry_cache
    snapshot = latest_telemetry
    with _telemetry_cache_lock:
        if _telemetry_cache[0] is not snapshot:
            payload = app.json.dumps(snapshot, separators=(',', ':'), sort_keys=False).encode('utf-8')
            etag = hashlib.blake2s(payload, digest_size=12).hexdigest()
            _telemetry_cache = (snapshot, payload, gzip.compress(payload, compresslevel=1), etag)
        payload = _telemetry_cache[1]
        compressed, etag = _telemetry_cache[2:]
    headers = {'Cache-Control': 'no-cache', 'Vary': 'Accept-Encoding', 'ETag': '"' + etag + '"'}
    if request.if_none_match.contains(etag):
        return Response(status=304, headers=headers)
    if request.accept_encodings['gzip'] > 0:
        payload = compressed
        headers['Content-Encoding'] = 'gzip'
    return Response(payload, mimetype='application/json', headers=headers)

# 3. HTML GET Endpoint: Renders the external HTML file
@app.route('/', methods=['GET'])
def index():
    frontend_dist = Path(app.root_path) / 'frontend' / 'dist'
    if (frontend_dist / 'index.html').is_file():
        response = send_from_directory(frontend_dist, 'index.html')
        response.headers['Cache-Control'] = 'no-cache'
        return response
    return Response('Build the frontend first: cd frontend; npm install; npm run build',
                    status=503, mimetype='text/plain')


@app.route('/frontend/<path:filename>')
def frontend_asset(filename):
    # made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag
    response = send_from_directory(Path(app.root_path) / 'frontend' / 'dist', filename)
    response.headers['Cache-Control'] = ('public, max-age=31536000, immutable'
                                         if filename.startswith('assets/') else 'no-cache')
    return response


@app.route('/assets/<path:filename>')
def viewer_asset(filename):
    # made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag
    return send_from_directory(Path(app.root_path) / 'frontend' / 'assets', filename, max_age=86400)


@app.route('/api/viewer/config')
def viewer_configuration():
    import satellite_parameters as config
    active = latest_telemetry.get('spacecraft_model_url', config.SPACECRAFT.model_url)
    return jsonify(spacecraft_model_url=active, viewer_lighting=config.VIEWER,
                   pointing_strategy=config.POINTING['strategy'], legacy_mode=config.POINTING['legacy_mode'],
                   spacecraft_com=latest_telemetry.get('center_of_mass_body_m', config.GEOMETRY.center_of_mass_body_m))


@app.route('/api/spacecraft')
def spacecraft_configuration():
    import satellite_parameters as config
    return jsonify(configuration=latest_telemetry.get('spacecraft_configuration', config.SPACECRAFT.configuration),
                   model_url=latest_telemetry.get('spacecraft_model_url', config.SPACECRAFT.model_url),
                   mass_kg=latest_telemetry.get('spacecraft_mass_kg', config.MASS_KG),
                   center_of_mass_body_m=latest_telemetry.get('center_of_mass_body_m', config.GEOMETRY.center_of_mass_body_m))


@app.route('/ground/track/no/yaw/steering')
def index2():
    return redirect("/", code=302)


# ------------------ CONTROL INPUTS ------------------
@app.route('/update/control/inputs', methods=['POST'])
def update_control_inputs():

    data = request.get_json()
    label = data.get('label')   # 'yaw', 'pitch', 'roll'
    value = data.get('value')

    if label is None or value is None:
        return jsonify({"status": "error", "message": "Invalid payload"}), 400

    cs.set_control(label, value)

    yaw, pitch, roll = cs.get_controls()
    print(f"Current State -> Y: {yaw} | P: {pitch} | R: {roll}")

    return jsonify({"status": "success"})

# ------------------ CONTROL MODE ------------------
@app.route('/update/mode', methods=['POST'])
def update_mode():
    data = request.get_json()
    value = data.get('mode') if data else None
    if value not in cs.MODES:
        return jsonify({"status": "error", "message": "Invalid mode"}), 400
    try:
        cs.set_mode(value)
    except ValueError as error:
        return jsonify(error=str(error)), 400
    return jsonify({"status": "success", "mode": value})


@app.route("/rw_telemetry")
def rw_telemetry():
    return jsonify({
        "time": store.time,
        "mode": store.mode,
        "rw_torques": store.rw_torques.tolist()
    })

@app.route("/mtr_telemetry")
def mtr_telemetry():
    return jsonify({
        "time": store.time,
        "mode": store.mode,
        "mtr_torques": store.mtr_torques.tolist(),
        "mtr_dipole": store.mtr_dipole.tolist(),
        "mtr_currents": store.mtr_currents.tolist(),  
        #"angular_accelerations": np.degrees(store.angular_acceleration.tolist())
    })


'''
if __name__ == '__main__':    
 app.run(debug=True, port=5000)
'''

@app.route('/api/pointing', methods=['GET', 'POST'])
def pointing_input():
    if request.method == 'GET':
        return jsonify(strategy=cs.config.POINTING['strategy'], mode=cs.get_mode(), desired_quaternion=cs.get_pointing_target().tolist(), command_id=cs.get_pointing_command()['command_id'], applied_command_id=latest_telemetry.get('custom_command_id'))
    try:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValueError('Expected a JSON object')
        target = cs.set_pointing_input(data.get('quaternion'),
            input_kind=data.get('input', 'desired_quaternion'),
            reference_quaternion=data.get('reference_quaternion'))
        return jsonify(mode='CUSTOM', desired_quaternion=target, command_id=cs.get_pointing_command()['command_id'])
    except (ValueError, TypeError) as error:
        return jsonify(error=str(error)), 400

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, threaded=True, debug=False)
