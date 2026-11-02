"""Build a standalone exporter with its installer template (Windows)."""
import subprocess
import sys
import argparse
from pathlib import Path


def main():
    repo = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description='Build the standalone Windows exporter')
    parser.add_argument('--output-dir',type=Path,default=repo/'dist')
    output = parser.parse_args().output_dir.resolve()
    build = repo / "build/app"
    build.mkdir(parents=True, exist_ok=True)
    template_entry = build / "installer_entry.py"
    template_entry.write_text("from packforge.installer_ui import main\nmain()\n", encoding="utf-8")
    app_entry = build / "app_entry.py"
    app_entry.write_text("from packforge.__main__ import main\nraise SystemExit(main())\n", encoding="utf-8")
    common = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
              "--paths", str(repo), "--collect-data", "minecraft_launcher_lib", "--specpath", str(build),
              '--add-data', f"{repo / 'LICENSE'};."]
    subprocess.run(common + ["--name", "installer-template", "--distpath", str(build),
                            "--workpath", str(build / "template-work"), str(template_entry)], check=True)
    subprocess.run(common + ["--name", "PrismPackForge", "--distpath", str(output),
                            "--workpath", str(build / "app-work"), "--add-data",
                            f"{build / 'installer-template.exe'};.", str(app_entry)], check=True)
    print(output / "PrismPackForge.exe")


if __name__ == "__main__":
    main()
