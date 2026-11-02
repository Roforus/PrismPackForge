from __future__ import annotations

from .network import configure_application_tls
configure_application_tls()

import argparse
import os
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Prism Pack Forge — экспорт и установка сборок")
    commands = parser.add_subparsers(dest="command")
    export = commands.add_parser("export", help="Экспортировать экземпляр Prism")
    export.add_argument("instance", type=Path)
    export.add_argument("--id", required=True, dest="pack_id")
    export.add_argument("--name", required=True)
    export.add_argument("--version", required=True)
    export.add_argument("--output", type=Path, required=True, help="Путь к .pack.zip")
    export.add_argument("--include-options", action="store_true", help=argparse.SUPPRESS)
    export.add_argument("--exe", type=Path, help="Дополнительно собрать Windows EXE по этому пути")
    build = commands.add_parser("build", help="Собрать EXE из готового pack.zip")
    build.add_argument("bundle", type=Path)
    build.add_argument("--output", type=Path, required=True)
    installer = commands.add_parser("install", help="Установить или обновить сборку")
    installer.add_argument("bundle", type=Path)
    installer.add_argument("--launcher", choices=["prism", "legacy", "tlauncher"], required=True)
    installer.add_argument("--destination", type=Path, required=True)
    installer.add_argument("--replace-options", action="store_true")
    gui = commands.add_parser("installer", help="Открыть графический установщик для pack.zip")
    gui.add_argument("bundle", type=Path)
    args = parser.parse_args()
    try:
        if args.command is None:
            from .ui import main as gui_main
            gui_main()
        elif args.command == "export":
            from .exporter import build_exe, export_pack
            bundle = export_pack(args.instance, args.output, pack_id=args.pack_id, name=args.name,
                                 version=args.version,
                                 curseforge_key=os.environ.get("CURSEFORGE_API_KEY", ""))
            if args.exe:
                build_exe(bundle, args.exe)
        elif args.command == "build":
            from .exporter import build_exe
            from .installer import read_manifest
            read_manifest(args.bundle)
            build_exe(args.bundle, args.output)
        elif args.command == "install":
            from .installer import install
            install(args.bundle, args.destination, args.launcher, replace_options=args.replace_options)
        elif args.command == "installer":
            from .installer_ui import main as installer_main
            installer_main(args.bundle)
    except (Exception, KeyboardInterrupt) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
