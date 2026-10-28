import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
DATA_DIR = Path(os.environ.get("OMNI_DATA_DIR", "data")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
