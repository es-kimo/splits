import os
from pathlib import Path

DEFAULT_LOCAL_ENV_FILES = (".env.local", ".env")


def _parse_env_line(line):
    text = line.strip()
    if not text or text.startswith("#"):
        return None, None
    if text.startswith("export "):
        text = text[7:].strip()
    if "=" not in text:
        return None, None
    key, value = text.split("=", 1)
    key = key.strip()
    value = value.strip()
    if not key:
        return None, None
    if len(value) >= 2 and (
        (value[0] == "'" and value[-1] == "'")
        or (value[0] == '"' and value[-1] == '"')
    ):
        value = value[1:-1]
    return key, value


def load_local_env(files=DEFAULT_LOCAL_ENV_FILES, override=False):
    loaded = []
    for file_name in files:
        path = Path(file_name)
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            key, value = _parse_env_line(raw_line)
            if not key:
                continue
            if not override and key in os.environ:
                continue
            os.environ[key] = value
            loaded.append(key)
    return loaded
