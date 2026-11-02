from __future__ import annotations

from .network import configure_application_tls
configure_application_tls()

import queue
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .installer import install, read_manifest
from .discovery import DOWNLOADS, NAMES, discover, installation_at, launcher_kind
from .ui import Window


def main(bundle: Path | None = None):
    if bundle is None:
        payload = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "payload"
        bundles = list(payload.glob("*.zip"))
        if len(bundles) == 1:
            bundle = bundles[0]
        else:
            picker = tk.Tk()
            picker.withdraw()
            selected = filedialog.askopenfilename(title="Сборка", filetypes=[("Pack ZIP", "*.zip")])
            picker.destroy()
            if not selected:
                return
            bundle = Path(selected)
    try:
        manifest = read_manifest(bundle)
    except Exception as exc:
        picker = tk.Tk()
        picker.withdraw()
        messagebox.showerror("Повреждённая сборка", str(exc))
        picker.destroy()
        return
    window = Window(f"{manifest['name']} — установщик")
    ttk.Label(window.frame, text=f"{manifest['name']} · {manifest['version']}",
              font=("Segoe UI", 18, "bold")).grid(row=0, column=0, columnspan=3, sticky="w", pady=12)
    loaders = ", ".join(f"{x['name']} {x['version']}" for x in manifest.get("loaders", [])) or "Vanilla"
    ttk.Label(window.frame, text=f"Minecraft {manifest['minecraft']} · {loaders}").grid(
        row=1, column=0, columnspan=3, sticky="w", pady=8)
    status = tk.StringVar(value="Поиск установленной сборки и лаунчеров…")
    ttk.Label(window.frame, textvariable=status, wraplength=750).grid(
        row=2, column=0, columnspan=3, sticky="w", pady=8)
    toolbar = ttk.Frame(window.frame)
    toolbar.grid(row=3, column=0, columnspan=3, sticky="ew", pady=5)
    ttk.Label(window.frame, text="Лаунчер / действие").grid(row=4, column=0, sticky="w")
    selection = tk.StringVar()
    combo = ttk.Combobox(window.frame, textvariable=selection, state="disabled")
    combo.grid(row=4, column=1, columnspan=2, sticky="ew", padx=10, pady=8)
    choices = {}
    portable_paths = []
    search_roots = [Path.cwd(), Path(sys.executable).parent if getattr(sys, "frozen", False) else bundle.parent]
    scanning = False
    scan_events = queue.Queue()

    def browse_destination(variable):
        selected = filedialog.askdirectory(title="Папка экземпляра Prism или игровая папка лаунчера")
        if selected:
            variable.set(selected)
            if installation_at(Path(selected), manifest["id"]):
                search_roots.insert(0, Path(selected))
                refresh()

    destination = window.field(5, "Папка установки", browse=browse_destination)
    instruction = tk.StringVar()
    ttk.Label(window.frame, textvariable=instruction, wraplength=750).grid(
        row=6, column=0, columnspan=3, sticky="w", pady=8)

    downloads = ttk.LabelFrame(window.frame, text="Установите лаунчер и повторите поиск", padding=8)
    for column, kind in enumerate(NAMES):
        label = NAMES[kind] + (" — рекомендуется" if kind == "prism" else "")
        ttk.Button(downloads, text=label, command=lambda k=kind: webbrowser.open(DOWNLOADS[k])).grid(
            row=0, column=column, padx=4)

    def change(_event=None):
        choice = choices.get(selection.get())
        if not choice:
            return
        mode, kind, default, version = choice
        destination.set(str(default))
        if mode == "update":
            status.set(f"Найдена сборка {manifest['name']} версии {version}. Рекомендуется обновление "
                       f"до {manifest['version']} в прежней папке.")
            window.button.configure(text="Обновить сборку")
        else:
            status.set(f"Новая установка: {NAMES[kind]}. Приоритет: Prism → Legacy → TLauncher.")
            window.button.configure(text="Установить сборку")
        if kind == "prism":
            instruction.set("Укажите НОВУЮ папку экземпляра внутри каталога instances Prism. "
                            "Для обновления выберите папку предыдущей установки. "
                            "При нестандартном или portable Prism выберите путь вручную. "
                            "Minecraft и загрузчик Prism скачает при первом запуске.")
        else:
            instruction.set("Укажите игровую папку, заданную в настройках лаунчера (в ней будет каталог versions). "
                            f"Установщик автоматически скачает Minecraft {manifest['minecraft']}, {loaders} "
                            "и файлы сборки. Предварительный запуск игры не требуется. "
                            "После установки перезапустите лаунчер и выберите версию, указанную в журнале. "
                            "Путь должен совпадать с настройками лаунчера. В Legacy отключите разделение по подпапкам; "
                            "для сборки задайте отдельную игровую папку.")
    combo.bind("<<ComboboxSelected>>", change)

    def apply_scan(result):
        choices.clear()
        for number, found in enumerate(result.installations, 1):
            label = f"Обновить: {NAMES[found.launcher]} · версия {found.version} · #{number}"
            choices[label] = ("update", found.launcher, found.destination, found.version)
        for launcher in result.launchers:
            recommended = launcher == result.recommended_launcher
            label = f"Установить: {launcher.name}" + (" (рекомендуется)" if recommended else "")
            if launcher.kind == "prism":
                default = launcher.instances_dir / manifest["id"]
            else:
                default = launcher.game_roots[0]
            choices[label] = ("install", launcher.kind, default, "")
        combo.configure(values=list(choices), state="readonly" if choices else "disabled")
        downloads.grid_forget()
        if choices:
            selection.set(next(iter(choices)))
            window.button.configure(state="normal")
            change()
        else:
            selection.set("")
            destination.set("")
            status.set("Сборка и поддерживаемые лаунчеры не найдены. Рекомендуется Prism Launcher.")
            instruction.set("Скачайте и установите один из лаунчеров по официальной ссылке ниже, "
                            "затем нажмите «Повторить поиск». Если у вас portable-лаунчер, "
                            "выберите его кнопкой «Указать лаунчер…».")
            downloads.grid(row=7, column=0, columnspan=3, sticky="ew", pady=5)
            window.button.configure(state="disabled")

    def refresh():
        nonlocal scanning
        if window.busy or scanning:
            return
        scanning = True
        window.button.configure(state="disabled")
        combo.configure(state="disabled")
        status.set("Поиск установленной сборки и лаунчеров…")
        paths, roots = list(portable_paths), list(search_roots)

        def worker():
            try:
                scan_events.put((discover(manifest["id"], portable_paths=paths, search_roots=roots), None))
            except Exception as exc:
                scan_events.put((None, exc))
        threading.Thread(target=worker, daemon=True).start()

    def poll_scan():
        nonlocal scanning
        try:
            result, error = scan_events.get_nowait()
        except queue.Empty:
            pass
        else:
            scanning = False
            if error:
                status.set(f"Ошибка поиска: {error}. Повторите поиск или укажите папку вручную.")
                window.button.configure(state="disabled")
            else:
                apply_scan(result)
        window.root.after(100, poll_scan)

    def add_launcher():
        if window.busy or scanning:
            return
        selected = filedialog.askopenfilename(title="Выберите файл установленного portable-лаунчера",
                                              filetypes=[("Лаунчер", "*.exe *.jar")])
        if selected:
            path = Path(selected)
            if not launcher_kind(path):
                messagebox.showerror("Не удалось определить лаунчер", "Выберите PrismLauncher.exe, "
                                     "LegacyLauncher.exe/.jar или TLauncher.exe/.jar. Установщик лаунчера не подходит.")
                return
            portable_paths.insert(0, path)
            refresh()

    def add_search_root():
        if window.busy or scanning:
            return
        selected = filedialog.askdirectory(title="Где искать ранее установленную сборку?")
        if selected:
            search_roots.insert(0, Path(selected))
            refresh()

    ttk.Button(toolbar, text="Повторить поиск", command=refresh).pack(side="left", padx=(0, 6))
    ttk.Button(toolbar, text="Указать лаунчер…", command=add_launcher).pack(side="left", padx=6)
    ttk.Button(toolbar, text="Найти сборку в папке…", command=add_search_root).pack(side="left", padx=6)
    replace = tk.BooleanVar(value=False)
    has_options = any(f["path"] == "options.txt" for f in manifest["files"])
    ttk.Checkbutton(window.frame, text="Заменить настройки игры при обновлении (при первой установке — обязательно)",
                    variable=replace, state="normal" if has_options else "disabled").grid(
        row=8, column=0, columnspan=3, sticky="w", pady=8)
    ttk.Label(window.frame, text="Закройте игру и лаунчер перед установкой. Для каждой сборки используйте отдельную папку.\n"
              "Моды скачиваются из Modrinth/CurseForge. Для установки нужен интернет.\n"
              "Обновление сохраняет существующие настройки игры, пока не выбрана их замена.",
              wraplength=750).grid(row=9, column=0, columnspan=3, sticky="w", pady=6)

    def start():
        if scanning or selection.get() not in choices:
            return
        if not destination.get().strip():
            messagebox.showerror("Папка не выбрана", "Укажите папку игры выбранного профиля.")
            return
        target = Path(destination.get())
        action, mode, _, _ = choices[selection.get()]
        existing = installation_at(target, manifest["id"])
        if action == "update" and (not existing or existing.launcher != mode):
            messagebox.showerror("Сборка не найдена", "В выбранной папке нет этой сборки. "
                                 "Для новой копии выберите «Установить» в списке действий.")
            return
        if existing and existing.launcher != mode:
            messagebox.showerror("Другой лаунчер", f"Эта сборка установлена для {NAMES[existing.launcher]}. "
                                 "Выберите её в списке обновлений.")
            return
        overwrite = replace.get()
        window.run_task(lambda log: install(bundle, target, mode, replace_options=overwrite, log=log))

    window.finish_layout(10, "Установить / обновить", start)
    window.root.geometry("900x820")
    window.root.minsize(820, 760)
    window.button.configure(state="disabled")
    window.root.after(100, poll_scan)
    window.root.after(0, refresh)
    window.root.mainloop()
