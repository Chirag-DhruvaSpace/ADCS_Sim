# Working preferences

Write code as if a human teammate will read and maintain it.

- Prefer simple, direct logic, meaningful names, and small functions.
- Explain the reason for non-obvious decisions; avoid comments that repeat code.
- Avoid unnecessary abstractions, one-letter names, deep nesting, and clever tricks.
- Keep propagation, forces/torques, sensors, actuators, and coordinate transforms separate.
- Use SI units internally and document units. Convert to device counts only at sensor interfaces.
- Keep sensor acquisition separate from navigation processing.
- Keep sensor models and their helpers inside simulateimu.py, simulategps.py,
  simulatesunsensor.py, imu_navigation.py, and gps_navigation.py. Do not split
  helpers or demos into additional modules merely to shorten these files.
- Send raw sensor readings as JSON over TCP. Do not introduce a binary packet layer.
- Firmware at C:\Projects\Firmware\Leap_2_ADCS_Firmware_V1 is read-only unless
  the user explicitly authorizes firmware edits.
- Do not leave a compiled receiver executable beside the receiver C source.
