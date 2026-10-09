import os
from pathlib import Path

import orekit_jpype

fspath = getattr(os, 'fspath', str)

jar_path_glob = Path(orekit_jpype.__file__).parent.joinpath("jars", "*.jar")

datas = [[fspath(jar_path_glob), os.path.join("orekit_jpype", "jars")]]
