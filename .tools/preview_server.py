import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
source=Path('validation/cad-telemetry.json')
app.latest_telemetry=json.loads(source.read_text(encoding='utf-8'))[-1]
app.app.run(port=5012,debug=False)
