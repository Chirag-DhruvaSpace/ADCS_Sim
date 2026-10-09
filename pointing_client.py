"""Real-time pointing client for another Python process."""
import requests


def send_pointing_input(quaternion, *, quaternion_error=False,
                        reference_quaternion=None, url='http://127.0.0.1:5000'):
    payload = {'input': 'quaternion_error' if quaternion_error else 'desired_quaternion',
               'quaternion': list(quaternion)}
    if reference_quaternion is not None:
        payload['reference_quaternion'] = list(reference_quaternion)
    response = requests.post(url + '/api/pointing', json=payload, timeout=2)
    response.raise_for_status()
    return response.json()
