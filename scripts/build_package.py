"""Собрать пакет обновления Пульта для салона.

    python3 scripts/build_package.py 9.23.0 /home/claude/pkg

Пакет 9.22.4/9.22.5 собирали вручную и потеряли миграции, исходники
интерфейса и Dockerfile (инцидент 19.10.2026). Теперь пакет собирается
только этим скриптом, и он отказывается выпускать неполный пакет.
"""

import re
import shutil
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# Что не едет в салон: зависимости, кэши, сборки (интерфейс собирается в
# образе), рабочие данные и серверная часть hub.
EXCLUDE = {".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache",
           ".ruff_cache", ".mypy_cache", "dist", "static", "output", "hub"}
EXCLUDE_FILES = {".env"}
MUST_EXIST = ["backend/alembic.ini", "backend/app/main.py", "backend/pyproject.toml", "backend/uv.lock",
              "frontend/src", "frontend/dist/index.html", "frontend/package.json", "frontend/package-lock.json", "frontend/index.html",
              "local/Dockerfile", "local/docker-compose.yml", ".dockerignore", ".env.example"]
EXTRAS = REPO / "local" / "package"  # UPDATE.bat, FIX-DB.bat, fix_db.py, README.txt


def fail(msg: str) -> None:
    sys.exit(f"ПАКЕТ НЕ СОБРАН: {msg}")


def main(version: str, out: Path) -> Path:
    main_py = (REPO / "backend/app/main.py").read_text(encoding="utf-8")
    m = re.search(r'^APP_VERSION = "([^"]+)"', main_py, re.M)
    if not m or m.group(1) != version:
        fail(f"APP_VERSION в main.py = {m.group(1) if m else '?'}, а собираем {version}")

    name = f"Rubl-Director-{version}"
    root = out / name
    shutil.rmtree(root, ignore_errors=True)
    app = root / "app"

    # Интерфейс собираем здесь, а не на салоне: npm в Docker там зависал
    # (30.10.2026). В пакет едет готовый frontend/dist.
    import subprocess, time
    started = time.time()
    r = subprocess.run(["npm", "run", "build"], cwd=REPO / "frontend", capture_output=True, text=True)
    index = REPO / "frontend/dist/index.html"
    if r.returncode != 0 or not index.exists() or index.stat().st_mtime < started:
        fail(f"интерфейс не собрался:\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}")

    def ignore(d, names):
        keep_dist = Path(d).name == "frontend"
        return [n for n in names
                if (n in EXCLUDE and not (keep_dist and n == "dist"))
                or n in EXCLUDE_FILES or n.endswith((".pyc", ".pyo"))]

    app.mkdir(parents=True)
    for item in REPO.iterdir():
        if item.name in EXCLUDE or item.name in EXCLUDE_FILES:
            continue
        dst = app / item.name
        if item.is_dir():
            shutil.copytree(item, dst, ignore=ignore)
        else:
            shutil.copy2(item, dst)
    shutil.rmtree(app / "local" / "package", ignore_errors=True)
    shutil.rmtree(app / "local" / "installer", ignore_errors=True)

    # ── проверки ──
    for rel in MUST_EXIST:
        if not (app / rel).exists():
            fail(f"нет {rel}")
    repo_mig = sorted(p.name for p in (REPO / "backend/alembic/versions").glob("0*.py"))
    pkg_mig = sorted(p.name for p in (app / "backend/alembic/versions").glob("0*.py"))
    if repo_mig != pkg_mig or not pkg_mig:
        fail(f"миграции: в коде {len(repo_mig)}, в пакете {len(pkg_mig)}")

    for f in EXTRAS.iterdir():
        shutil.copy2(f, root / f.name)
    for bat in root.glob("*.bat"):
        raw = bat.read_bytes()
        if any(b > 127 for b in raw):
            fail(f"{bat.name}: в .bat только латиница, иначе cmd ломает разбор")
        bat.write_bytes(raw.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    # Mac: скрипты с переводом строки LF и правом на запуск — иначе двойной
    # щелчок по .command не сработает. zipfile сохраняет право в архиве.
    for sh in [*root.rglob("*.sh"), *root.rglob("*.command")]:
        raw = sh.read_bytes()
        if b"\r\n" in raw:
            fail(f"{sh.name}: переводы строк CRLF, на Mac не запустится")
        sh.chmod(0o755)

    # ── архив: zipfile сам ставит флаг UTF-8 русским именам ──
    zpath = out / f"{name}.zip"
    zpath.unlink(missing_ok=True)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(root.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(out).as_posix())
    with zipfile.ZipFile(zpath) as z:
        bad = [i.filename for i in z.infolist()
               if any(ord(c) > 127 for c in i.filename) and not i.flag_bits & 0x800]
    if bad:
        fail(f"русские имена без флага UTF-8: {bad[:3]}")
    print(f"OK {zpath} · миграций {len(pkg_mig)} · файлов {sum(1 for p in root.rglob('*') if p.is_file())}")

    # Установщик для Windows: тот же пакет одним файлом (local/installer/update.nsi).
    if shutil.which("makensis"):
        import subprocess
        exe = out / f"Установка-Пульт-{version}.exe"
        exe.unlink(missing_ok=True)
        r = subprocess.run(["makensis", "-V2", f"-DVERSION={version}", f"-DSRC={root}", f"-DOUT={exe}",
                            "update.nsi"], cwd=REPO / "local" / "installer", capture_output=True, text=True)
        if r.returncode != 0 or not exe.exists():
            fail(f"установщик не собрался:\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")
        print(f"OK {exe} · {exe.stat().st_size // 1024} КБ")
    else:
        print("makensis не найден — установщик .exe не собран")
    return zpath


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1], Path(sys.argv[2] if len(sys.argv) > 2 else "."))
