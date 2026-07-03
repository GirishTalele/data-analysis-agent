import sys
from pathlib import Path

# `python -m src` only puts the project ROOT on sys.path, not src/ itself, so
# the bare "api" module name (and its siblings: db, graph, config, ...) would
# fail to import. Insert this file's own directory (src/) so they resolve as
# top-level modules exactly like they do under pytest's pythonpath setting.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn

if __name__ == "__main__":
    uvicorn.run("api:app", host="0.0.0.0", port=8001, reload=False)
