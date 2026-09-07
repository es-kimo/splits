from __future__ import annotations

import argparse
import subprocess
from pathlib import PurePosixPath

VERSION_FILE = "rating/replay/version.py"
IDENTITY_AFFECTING_PREFIXES = (
    "rating/engine/",
    "rating/replay/checkpoint.py",
    "rating/replay/orchestrator.py",
    "rating/replay/snapshot.py",
    "rating/calibration/",
)


def requires_version_bump(paths: set[str]) -> bool:
    return any(
        path != VERSION_FILE and any(path.startswith(prefix) for prefix in IDENTITY_AFFECTING_PREFIXES)
        for path in paths
    )


def changed_paths(base: str) -> set[str]:
    completed = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return {PurePosixPath(line).as_posix() for line in completed.stdout.splitlines() if line}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="레이팅 엔진 변경 시 수동 알고리즘 버전 갱신을 검사합니다.")
    parser.add_argument("--base", help="비교 기준 Git ref")
    parser.add_argument("--changed-file", action="append", default=[], help="테스트용 변경 파일 경로")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    paths = {PurePosixPath(path).as_posix() for path in args.changed_file}
    if args.base:
        paths.update(changed_paths(args.base))
    if not paths:
        raise SystemExit("[error] --base 또는 --changed-file이 필요합니다.")
    if requires_version_bump(paths) and VERSION_FILE not in paths:
        raise SystemExit(
            "[error] 레이팅 엔진/리플레이/보정 코드가 변경되었습니다. "
            "rating/replay/version.py의 ALGORITHM_VERSION도 갱신하세요."
        )
    print("[ok] rating algorithm version guard passed")


if __name__ == "__main__":
    main()
