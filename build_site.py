import shutil
import subprocess
from pathlib import Path

SITE_DATA_DIR = Path("site/data")
WEB_DIR = Path("web")
DIST_DIR = WEB_DIR / "dist"
REQUIRED_JSON = [
    SITE_DATA_DIR / "athletes.json",
    SITE_DATA_DIR / "meets.json",
    SITE_DATA_DIR / "distribution.json",
    SITE_DATA_DIR / "meta.json",
]
SYNC_TARGETS = [
    Path("index.html"),
    Path("athlete"),
    Path("meet"),
    Path("distribution"),
    Path("privacy"),
    Path("sitemap.xml"),
    Path("robots.txt"),
    Path("support.js"),
]


def ensure_contract_files():
    for path in REQUIRED_JSON:
        if not path.exists():
            raise FileNotFoundError(f"[error] 파일이 없습니다: {path}")


def remove_path(path):
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def clean_previous_outputs():
    for path in SYNC_TARGETS:
        remove_path(path)


def run_astro_build():
    if not WEB_DIR.exists():
        raise FileNotFoundError(f"[error] 디렉터리가 없습니다: {WEB_DIR}")
    command = ["npm", "run", "build", "--prefix", str(WEB_DIR)]
    subprocess.run(command, check=True)


def copy_dist_to_root():
    if not DIST_DIR.exists():
        raise FileNotFoundError(f"[error] 빌드 결과 디렉터리가 없습니다: {DIST_DIR}")

    copied = []
    for child in DIST_DIR.iterdir():
        destination = Path(child.name)
        remove_path(destination)
        if child.is_dir():
            shutil.copytree(child, destination)
        else:
            shutil.copy2(child, destination)
        copied.append(destination)
    return copied


def main():
    try:
        ensure_contract_files()
        run_astro_build()
        clean_previous_outputs()
        copied = copy_dist_to_root()
    except FileNotFoundError as exc:
        print(str(exc))
        return
    except subprocess.CalledProcessError as exc:
        print(f"[error] Astro 빌드 실패: exit code {exc.returncode}")
        return

    for path in copied:
        print(f"[ok] 생성 완료: {path}")


if __name__ == "__main__":
    main()
