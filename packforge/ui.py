from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from .exporter import build_exe, export_pack


class Window:
    def __init__(self, title: str):
        from .appearance import load_theme
        self.root = tk.Tk()
        self.root.title(title)
        self.root.geometry("820x670")
        self.root.minsize(720, 600)
        self.theme = load_theme()
        topbar = ttk.Frame(self.root, padding=(10,4))
        topbar.pack(fill='x')
        self.theme_button = ttk.Button(topbar,text='Тёмная тема',command=self.toggle_theme)
        self.theme_button.pack(side='right')
        self.frame = ttk.Frame(self.root, padding=20)
        self.frame.pack(fill="both", expand=True)
        self.frame.columnconfigure(1, weight=1)
        self.events = queue.Queue()
        self.busy = False
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after_idle(self.apply_appearance)

    def apply_appearance(self):
        from .appearance import apply_theme
        apply_theme(self.root,self.theme)
        self.theme_button.configure(text='Светлая тема' if self.theme == 'dark' else 'Тёмная тема')

    def toggle_theme(self):
        from .appearance import save_theme
        self.theme = 'dark' if self.theme == 'light' else 'light'
        self.apply_appearance()
        try:
            save_theme(self.theme)
        except OSError:
            pass

    def close(self):
        if self.busy:
            messagebox.showinfo("Операция выполняется", "Дождитесь завершения операции.")
        else:
            self.root.destroy()

    def field(self, row, label, value="", *, browse=None, secret=False):
        ttk.Label(self.frame, text=label).grid(row=row, column=0, sticky="w", pady=7)
        variable = tk.StringVar(value=value)
        ttk.Entry(self.frame, textvariable=variable, show="*" if secret else "").grid(
            row=row, column=1, sticky="ew", padx=10)
        if browse:
            ttk.Button(self.frame, text="Обзор…", command=lambda: browse(variable)).grid(row=row, column=2)
        return variable

    def finish_layout(self, row, caption, command):
        self.button = ttk.Button(self.frame, text=caption, command=command)
        self.button.grid(row=row, column=0, columnspan=3, sticky="ew", pady=12)
        self.progress = ttk.Progressbar(self.frame, mode="indeterminate")
        self.progress.grid(row=row + 1, column=0, columnspan=3, sticky="ew")
        self.output = ScrolledText(self.frame, height=12, wrap="word", state="disabled")
        self.output.grid(row=row + 2, column=0, columnspan=3, sticky="nsew", pady=12)
        self.frame.rowconfigure(row + 2, weight=1)
        self.root.after(100, self.poll)

    def run_task(self, fn):
        if self.busy:
            return
        self.busy = True
        self.button.configure(state="disabled")
        self.progress.start()

        def worker():
            try:
                fn(lambda text: self.events.put(("log", str(text))))
                self.events.put(("done", "Готово"))
            except Exception as exc:
                self.events.put(("error", str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        while not self.events.empty():
            kind, text = self.events.get_nowait()
            self.output.configure(state="normal")
            self.output.insert("end", text + "\n")
            self.output.see("end")
            self.output.configure(state="disabled")
            if kind in ("done", "error"):
                self.busy = False
                self.button.configure(state="normal")
                self.progress.stop()
                if kind == "error":
                    messagebox.showerror("Ошибка", text)
        self.root.after(100, self.poll)


def directory(variable):
    value = filedialog.askdirectory()
    if value:
        variable.set(value)


def main():
    from .preferences import load_settings, save_settings
    from .prism_instances import list_instances
    from .exporter import slug
    settings = load_settings()
    profiles = settings.get('profiles', {})
    if not isinstance(profiles, dict):
        profiles = {}
    prism_roots = settings.get('prism_roots', [])
    if not isinstance(prism_roots, list):
        prism_roots = []
    prism_roots = [p for p in prism_roots if isinstance(p, str)]
    window = Window("Prism Pack Forge — экспорт сборки")
    ttk.Label(window.frame, text="Экспорт модовой сборки", font=("Segoe UI", 18, "bold")).grid(
        row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))
    instance = tk.StringVar()
    selected = tk.StringVar()
    ttk.Label(window.frame, text="Сборка / игровая папка").grid(row=1, column=0, sticky='w')
    selector = ttk.Combobox(window.frame, textvariable=selected, state='readonly')
    selector.grid(row=1, column=1, columnspan=2, sticky='ew', padx=10, pady=7)
    toolbar = ttk.Frame(window.frame)
    toolbar.grid(row=2, column=0, columnspan=3, sticky='w')
    pack_id = window.field(3, "Постоянный ID сборки", "my-pack")
    name = window.field(4, "Название", "Моя сборка")
    version = window.field(5, "Версия сборки", "1.0.0")
    output = window.field(6, "Папка результата", str(Path.cwd() / "dist"), browse=directory)
    key = window.field(7, "CurseForge API key", os.environ.get("CURSEFORGE_API_KEY", ""), secret=True)
    mc = window.field(8,'Minecraft (для игровой папки)')
    loader_version = window.field(9,'Версия модлоадера')
    ttk.Label(window.frame,text='Модлоадер (для игровой папки)').grid(row=10,column=0,sticky='w')
    loader = tk.StringVar(value='')
    ttk.Combobox(window.frame,textvariable=loader,state='readonly',
        values=['Vanilla','Fabric','Forge','NeoForge','Quilt']).grid(row=10,column=1,sticky='ew',padx=10)
    exe = tk.BooleanVar(value=True)
    ttk.Label(window.frame, text="options.txt всегда включается и применяется при первой установке").grid(
        row=11, column=0, columnspan=3, sticky="w", pady=5)
    ttk.Checkbutton(window.frame, text="Собрать EXE установщик", variable=exe).grid(
        row=12, column=0, columnspan=3, sticky="w", pady=5)
    ttk.Label(window.frame, text="ID сохраняйте между обновлениями. Параметры запоминаются отдельно для каждой сборки.\n"
              "Экспортируются моды, конфиги, скрипты, ресурсы и шейдеры; миры и аккаунты не включаются.",
              wraplength=750).grid(row=13, column=0, columnspan=3, sticky="w", pady=6)
    available = {}

    def remember():
        if instance.get():
            profiles[instance.get()] = dict(pack_id=pack_id.get(), name=name.get(), version=version.get(),
                output=output.get(), make_exe=exe.get(),minecraft=mc.get(),loader=loader.get(),loader_version=loader_version.get())
        try:
            save_settings(dict(last_instance=instance.get(), prism_roots=prism_roots,
                               game_roots=settings.get('game_roots',[]),profiles=profiles))
        except OSError as exc:
            window.events.put(('log', f'Не удалось сохранить параметры: {exc}'))

    def choose(_event=None):
        if window.busy:
            return
        remember()
        found = available.get(selected.get())
        if not found:
            return
        instance.set(str(found.path))
        saved = profiles.get(instance.get(), {})
        if not isinstance(saved, dict):
            saved = {}
        try:
            default_id = slug(found.path.name)
        except ValueError:
            default_id = 'my-pack'
        except Exception:
            default_id = 'my-pack'
        for variable, field, default in ((pack_id,'pack_id',default_id),(name,'name',found.name),
                (version,'version','1.0.0'),(output,'output',str(Path.cwd()/'dist'))):
            variable.set(saved.get(field,default))
        exe.set(saved.get('make_exe',True) is True)
        mc.set(saved.get('minecraft',''))
        loader.set(saved.get('loader',''))
        loader_version.set(saved.get('loader_version',''))
        remember()

    def refresh(preferred=None):
        if window.busy:
            return
        previous = preferred or instance.get() or settings.get('last_instance')
        available.clear()
        for found in list_instances(prism_roots):
            available[f'{found.name} — {found.path}'] = found
        from .prism_instances import PrismInstance
        for path in settings.get('game_roots',[]):
            if isinstance(path,str) and Path(path).is_dir():
                available[f'Игровая папка: {Path(path).name} — {path}'] = PrismInstance(Path(path),Path(path).name)
        selector.configure(values=list(available))
        label = next((k for k,v in available.items() if str(v.path)==previous), next(iter(available),''))
        selected.set(label)
        if label:
            choose()
        else:
            instance.set('')
            selected.set('Сборки не найдены — укажите папку Prism')

    def add_root():
        if window.busy:
            return
        folder = filedialog.askdirectory(title='Папка Prism Launcher или каталог instances')
        if folder:
            if folder not in prism_roots:
                prism_roots.append(folder)
            refresh()
            remember()

    selector.bind('<<ComboboxSelected>>',choose)
    ttk.Button(toolbar,text='Обновить список',command=refresh).pack(side='left',padx=4)
    ttk.Button(toolbar,text='Указать папку Prism…',command=add_root).pack(side='left',padx=4)
    def add_game():
        if window.busy:
            return
        folder = filedialog.askdirectory(title='Игровая папка из CurseForge, Modrinth App или другого лаунчера (с mods и options.txt)')
        if folder:
            remember()
            roots = settings.setdefault('game_roots',[])
            if folder not in roots:
                roots.append(folder)
            refresh(folder)
    ttk.Button(toolbar,text='Игровая папка другого лаунчера…',command=add_game).pack(side='left',padx=4)

    def start():
        from .exporter import slug
        try:
            if not instance.get().strip() or not output.get().strip():
                raise ValueError("Укажите папку экземпляра и папку результата")
            values = dict(instance=Path(instance.get()), pack_id=slug(pack_id.get()), name=name.get(),
                          version=version.get(), curseforge_key=key.get(),minecraft=mc.get(),
                          loader=loader.get(),loader_version=loader_version.get())
            folder = Path(output.get())
            make_exe = exe.get()
        except Exception as exc:
            messagebox.showerror("Проверьте поля", str(exc))
            return

        def task(log):
            bundle = export_pack(output=folder / f"{values['pack_id']}.pack.zip", log=log, **values)
            if make_exe:
                build_exe(bundle, folder / f"{values['pack_id']}-setup.exe", log)
        remember()
        window.run_task(task)

    window.finish_layout(14, "Экспортировать сборку", start)
    close = window.close
    def close_exporter():
        if not window.busy:
            remember()
        close()
    window.root.protocol('WM_DELETE_WINDOW',close_exporter)
    window.root.geometry('1000x900')
    refresh()
    window.root.mainloop()
