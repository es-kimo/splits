from __future__ import annotations

import hashlib
import math
from decimal import Decimal
from pathlib import Path
from typing import Mapping, Sequence


class SnapshotError(ValueError):
    """Inputs cannot be represented safely in a content address."""


def canonical_json(value: object) -> str:
    """Serialize JSON-compatible data with sorted keys and fixed float notation."""

    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SnapshotError("[error] 콘텐츠 주소의 부동소수 값은 유한해야 합니다.")
        if value == 0.0:
            value = 0.0
        return format(Decimal.from_float(value), "f")
    if isinstance(value, str):
        return _quote_string(value)
    if isinstance(value, Mapping):
        items: list[tuple[str, object]] = []
        for key, item in value.items():
            if not isinstance(key, str):
                raise SnapshotError("[error] 콘텐츠 주소의 딕셔너리 키는 문자열이어야 합니다.")
            items.append((key, item))
        return "{" + ",".join(f"{_quote_string(key)}:{canonical_json(item)}" for key, item in sorted(items)) + "}"
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return "[" + ",".join(canonical_json(item) for item in value) + "]"
    raise SnapshotError(f"[error] 콘텐츠 주소에 지원하지 않는 값 형식입니다: {type(value).__name__}")


def _quote_string(value: str) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def digest_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def input_snapshot_id(root: Path) -> str:
    """Hash the relative paths and contents of every regular ledger input file."""

    root = root.expanduser()
    if not root.is_dir():
        raise FileNotFoundError(f"[error] 입력 스냅샷 디렉터리가 없습니다: {root}")
    files = sorted(path for path in root.rglob("*") if path.is_file())
    if not files:
        raise FileNotFoundError(f"[error] 입력 스냅샷 파일이 없습니다: {root}")
    hasher = hashlib.sha256()
    for path in files:
        hasher.update(path.relative_to(root).as_posix().encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(digest_file(path).encode("ascii"))
        hasher.update(b"\0")
    return hasher.hexdigest()


def run_id(
    *,
    algo_version: str,
    engine_params: Mapping[str, object],
    calibrator_spec: Mapping[str, object],
    input_id: str,
) -> str:
    if not algo_version.strip():
        raise SnapshotError("[error] algo_version은 비어 있을 수 없습니다.")
    if not input_id.strip():
        raise SnapshotError("[error] input_snapshot_id는 비어 있을 수 없습니다.")
    payload = b"\0".join(
        (
            algo_version.encode("utf-8"),
            canonical_json(engine_params).encode("utf-8"),
            canonical_json(calibrator_spec).encode("utf-8"),
            input_id.encode("ascii"),
        )
    )
    return hashlib.sha256(payload).hexdigest()[:16]
