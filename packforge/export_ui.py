"""Source-specific export form; advanced controls live in a settings dialog."""
import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .exporter import build_exe, export_pack, slug
from .preferences import load_settings, save_settings
from .prism_instances import list_instances
from .ui import Window
from .source_identity import source_id, validate_id

LAUNCHERS = ('Prism Launcher','MultiMC','CurseForge','Modrinth App','Minecraft Launcher',
             'Legacy Launcher','TLauncher','Другой лаунчер')
INSTANCE_LAUNCHERS = {'Prism Launcher':'prism','MultiMC':'multimc'}


class ExporterUI:
    def __init__(self):
        self.settings = load_settings()
        self.profiles = self.settings.get('profiles',{})
        if not isinstance(self.profiles,dict):
            self.profiles = {}
        last = self.settings.get('last_export',{})
        if isinstance(last,dict) and isinstance(last.get('instance'),str) and Path(last['instance']).is_dir():
            self.settings['last_instance'] = last['instance']
            self.settings['last_launcher'] = last.get('launcher','Prism Launcher')
            self.profiles[last['instance']] = last.copy()
        self.roots = self.settings.get('prism_roots',[])
        if not isinstance(self.roots,list):
            self.roots = []
        self.window = Window('Prism Pack Forge')
        w = self.window
        w.root.geometry('860x760')
        ttk.Button(w.topbar,text='Настройки',command=self.open_settings).pack(side='right',padx=6)
        self.launcher = tk.StringVar(value=self.settings.get('last_launcher','Prism Launcher'))
        if self.launcher.get() not in LAUNCHERS:
            self.launcher.set('Prism Launcher')
        self.instance = tk.StringVar()
        self.folder = tk.StringVar()
        self.selected = tk.StringVar()
        self.pack_id = tk.StringVar(value='my-pack')
        self.source_id = None
        self.name = tk.StringVar()
        self.version = tk.StringVar(value='1.0.0')
        self.output = tk.StringVar(value=str(Path.cwd()/'dist'))
        self.mc = tk.StringVar()
        self.loader = tk.StringVar()
        self.loader_version = tk.StringVar()
        self.key = tk.StringVar(value=os.environ.get('CURSEFORGE_API_KEY',''))
        self.make_exe = tk.BooleanVar(value=True)
        self.available = {}
        self.dialog = None
        ttk.Label(w.frame,text='Экспорт сборки',font=('Segoe UI',18,'bold')).grid(row=0,column=0,columnspan=3,sticky='w',pady=(0,14))
        self.source_group = self.group('Источник',1)
        ttk.Label(self.source_group,text='Лаунчер').grid(row=0,column=0,sticky='w',pady=5)
        self.launcher_combo = ttk.Combobox(self.source_group,textvariable=self.launcher,values=LAUNCHERS,state='readonly')
        self.launcher_combo.grid(row=0,column=1,columnspan=2,sticky='ew',padx=(12,0))
        self.launcher_combo.bind('<<ComboboxSelected>>',lambda _:self.change_launcher())
        self.instance_frame = ttk.Frame(self.source_group)
        self.instance_frame.columnconfigure(1,weight=1)
        ttk.Label(self.instance_frame,text='Сборка').grid(row=0,column=0,sticky='w')
        self.instance_combo = ttk.Combobox(self.instance_frame,textvariable=self.selected,state='readonly')
        self.instance_combo.grid(row=0,column=1,sticky='ew',padx=12)
        self.instance_combo.bind('<<ComboboxSelected>>',lambda _:self.choose_instance())
        ttk.Button(self.instance_frame,text='↻',width=3,command=self.refresh).grid(row=0,column=2)
        self.game_frame = ttk.Frame(self.source_group)
        self.game_frame.columnconfigure(1,weight=1)
        self.entry(self.game_frame,0,'Игровая папка',self.folder,self.choose_game)
        self.entry(self.game_frame,1,'Minecraft',self.mc)
        ttk.Label(self.game_frame,text='Модлоадер').grid(row=2,column=0,sticky='w',pady=5)
        loader_combo = ttk.Combobox(self.game_frame,textvariable=self.loader,state='readonly',
                                  values=['Vanilla','Fabric','Forge','NeoForge','Quilt'])
        loader_combo.grid(row=2,column=1,columnspan=2,sticky='ew',padx=(12,0))
        loader_combo.bind('<<ComboboxSelected>>',lambda _:self.update_loader())
        self.loader_row = ttk.Frame(self.game_frame)
        self.loader_row.columnconfigure(1,weight=1)
        self.entry(self.loader_row,0,'Версия модлоадера',self.loader_version)
        self.package_group = self.group('Сборка',2)
        self.entry(self.package_group,0,'Название',self.name)
        self.entry(self.package_group,1,'Версия сборки',self.version)
        self.result_group = self.group('Результат',3)
        self.entry(self.result_group,0,'Папка сохранения',self.output,self.choose_output)
        w.finish_layout(4,'Экспортировать',self.start)
        w.output.configure(height=6)
        old_close = w.close
        def close():
            if not w.busy:
                self.remember()
            old_close()
        w.root.protocol('WM_DELETE_WINDOW',close)
        self.change_launcher(initial=True)

    def group(self,title,row):
        frame = ttk.LabelFrame(self.window.frame,text=title,padding=12)
        frame.columnconfigure(1,weight=1)
        frame.grid(row=row,column=0,columnspan=3,sticky='ew',pady=(0,10))
        return frame

    @staticmethod
    def entry(parent,row,label,variable,browse=None,secret=False):
        ttk.Label(parent,text=label).grid(row=row,column=0,sticky='w',pady=5)
        ttk.Entry(parent,textvariable=variable,show='*' if secret else '').grid(
            row=row,column=1,columnspan=1 if browse else 2,sticky='ew',padx=(12,0))
        if browse:
            ttk.Button(parent,text='…',width=3,command=browse).grid(row=row,column=2,padx=(6,0))

    def remember(self):
        if self.instance.get():
            self.profiles[self.instance.get()] = {
                'pack_id':self.pack_id.get(),'name':self.name.get(),'version':self.version.get(),
                'output':self.output.get(),'make_exe':self.make_exe.get(),'minecraft':self.mc.get(),
                'loader':self.loader.get(),'loader_version':self.loader_version.get()}
        self.settings.update(last_instance=self.instance.get(),last_launcher=self.launcher.get(),
                             prism_roots=self.roots,profiles=self.profiles)
        try:
            save_settings(self.settings)
        except OSError as exc:
            self.window.events.put(('log',f'Не удалось сохранить параметры: {exc}'))

    def load_profile(self,path,name):
        self.instance.set(str(path))
        saved = self.profiles.get(str(path),{})
        if not isinstance(saved,dict):
            saved = {}
        try:
            self.source_id = source_id(Path(path))
        except Exception as exc:
            self.source_id = None
            messagebox.showerror('ID исходной сборки',str(exc))
        self.pack_id.set(self.source_id or '')
        for variable,key,default in ((self.name,'name',name),
                (self.version,'version','1.0.0'),(self.output,'output',str(Path.cwd()/'dist')),
                (self.mc,'minecraft',''),(self.loader,'loader',''),(self.loader_version,'loader_version','')):
            variable.set(saved.get(key,default))
        self.make_exe.set(saved.get('make_exe',True) is True)
        self.update_loader()

    def change_launcher(self,initial=False):
        if not initial:
            self.remember()
        self.instance_frame.grid_remove()
        self.game_frame.grid_remove()
        if self.launcher.get() in INSTANCE_LAUNCHERS:
            self.instance_frame.grid(row=1,column=0,columnspan=3,sticky='ew',pady=(8,0))
            self.refresh(initial=initial)
        else:
            self.game_frame.grid(row=1,column=0,columnspan=3,sticky='ew',pady=(8,0))
            path = self.settings.get('last_instance','') if initial else ''
            if path and not (Path(path)/'mmc-pack.json').is_file():
                self.folder.set(path)
                self.load_profile(path,Path(path).name)
            else:
                self.folder.set('')
                self.instance.set('')
                self.mc.set('')
                self.loader.set('')
                self.update_loader()

    def update_loader(self):
        self.loader_row.grid_remove()
        if self.loader.get() and self.loader.get() != 'Vanilla':
            self.loader_row.grid(row=3,column=0,columnspan=3,sticky='ew')

    def refresh(self,initial=False):
        if self.window.busy:
            return
        previous = self.settings.get('last_instance','') if initial else self.instance.get()
        # Disambiguate equal instance names from different launcher roots.
        items = [i for i in list_instances(self.roots) if i.launcher == INSTANCE_LAUNCHERS[self.launcher.get()]]
        self.available = {f'{i.name} — {i.path}':i for i in items}
        self.instance_combo.configure(values=list(self.available))
        label = next((k for k,v in self.available.items() if str(v.path)==previous),next(iter(self.available),''))
        self.selected.set(label)
        if label:
            self.choose_instance()
        else:
            self.instance.set('')
            self.selected.set('Сборки не найдены — добавьте каталог в настройках')

    def choose_instance(self):
        if self.window.busy:
            return
        found = self.available.get(self.selected.get())
        if found:
            self.remember()
            self.load_profile(found.path,found.name)

    def choose_game(self):
        if self.window.busy:
            return
        path = filedialog.askdirectory(title=f'Игровая папка {self.launcher.get()} (mods и options.txt)')
        if path:
            self.remember()
            self.folder.set(path)
            self.load_profile(path,Path(path).name)

    def choose_output(self):
        path = filedialog.askdirectory(title='Папка результата')
        if path:
            self.output.set(path)

    def open_settings(self):
        if self.window.busy:
            return
        if self.dialog and self.dialog.winfo_exists():
            self.dialog.lift()
            return
        self.dialog = dialog = tk.Toplevel(self.window.root)
        dialog.title('Настройки')
        dialog.transient(self.window.root)
        dialog.grab_set()
        frame = ttk.Frame(dialog,padding=20)
        frame.pack(fill='both',expand=True)
        frame.columnconfigure(1,weight=1)
        self.entry(frame,0,'CurseForge API key',self.key,secret=True)
        ttk.Label(frame,text='Ключ используется только в текущем сеансе').grid(row=1,column=0,columnspan=3,sticky='w',pady=6)
        self.entry(frame,2,'Постоянный ID сборки',self.pack_id)
        ttk.Label(frame,text='ID читается из исходной сборки. Изменение сохранится при экспорте.').grid(row=3,column=0,columnspan=3,sticky='w',pady=6)
        ttk.Checkbutton(frame,text='Создавать EXE установщик',variable=self.make_exe).grid(row=4,column=0,columnspan=3,sticky='w',pady=6)
        ttk.Label(frame,text='Оформление').grid(row=5,column=0,sticky='w',pady=6)
        modes = {'Как в Windows':'system','Светлое':'light','Тёмное':'dark'}
        mode = tk.StringVar(value=next(k for k,v in modes.items() if v==self.window.theme_mode))
        combo = ttk.Combobox(frame,textvariable=mode,values=list(modes),state='readonly')
        combo.grid(row=5,column=1,columnspan=2,sticky='ew',padx=(12,0))
        combo.bind('<<ComboboxSelected>>',lambda _:self.window.set_theme_mode(modes[mode.get()]))
        def add_root():
            path = filedialog.askdirectory(parent=dialog,title='Каталог Prism/MultiMC или instances')
            if path and path not in self.roots:
                self.roots.append(path)
                if self.launcher.get() in INSTANCE_LAUNCHERS:
                    self.refresh()
        ttk.Button(frame,text='Добавить каталог Prism / MultiMC…',command=add_root).grid(row=6,column=0,columnspan=3,sticky='ew',pady=12)
        def done():
            self.remember()
            dialog.destroy()
        ttk.Button(frame,text='Готово',command=done).grid(row=7,column=0,columnspan=3,sticky='e')
        dialog.protocol('WM_DELETE_WINDOW',done)
        self.window.apply_appearance()

    def start(self):
        try:
            raw = self.launcher.get() not in INSTANCE_LAUNCHERS
            path = self.folder.get().strip() if raw else self.instance.get()
            if not path or not self.output.get().strip():
                raise ValueError('Выберите сборку и папку сохранения')
            if raw:
                from .sources import read_source
                read_source(Path(path),self.mc.get(),self.loader.get(),self.loader_version.get())
            if raw and str(Path(path)) != self.instance.get():
                self.instance.set(str(Path(path)))
            pack_id = source_id(Path(path)) if self.pack_id.get() == self.source_id else validate_id(self.pack_id.get())
            self.pack_id.set(pack_id)
            values = dict(instance=Path(path),pack_id=pack_id,name=self.name.get(),
                          version=self.version.get(),curseforge_key=self.key.get())
            if raw:
                values.update(minecraft=self.mc.get(),loader=self.loader.get(),loader_version=self.loader_version.get())
            output = Path(self.output.get())
            make_exe = self.make_exe.get()
        except Exception as exc:
            messagebox.showerror('Проверьте поля',str(exc))
            return
        self.remember()
        snapshot = dict(instance=str(Path(path).resolve()),launcher=self.launcher.get(),pack_id=pack_id,
            name=self.name.get(),version=self.version.get(),output=str(output.resolve()),make_exe=make_exe,
            minecraft=self.mc.get(),loader=self.loader.get(),loader_version=self.loader_version.get())
        def task(log):
            bundle = export_pack(output=output/f"{values['pack_id']}.pack.zip",log=log,**values)
            if make_exe:
                build_exe(bundle,output/f"{values['pack_id']}-setup.exe",log)
        def succeeded():
            from datetime import datetime, timezone
            snapshot['exported_at'] = datetime.now(timezone.utc).isoformat()
            self.settings['last_export'] = snapshot
            self.source_id = pack_id
            self.remember()
        self.window.run_task(task,on_success=succeeded)
