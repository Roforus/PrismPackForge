import json
import os
import tempfile
from pathlib import Path
from tkinter import ttk


def appearance_path():
    return Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.local/share'))) / 'PrismPackForge/appearance.json'


def system_theme():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
            return 'light' if winreg.QueryValueEx(key,'AppsUseLightTheme')[0] else 'dark'
    except (ImportError,OSError):
        return 'light'


def load_theme_mode():
    try:
        theme = json.loads(appearance_path().read_text('utf-8')).get('theme')
        return theme if theme in ('light','dark','system') else 'system'
    except (OSError,ValueError,AttributeError):
        return 'system'


def load_theme():
    mode = load_theme_mode()
    return system_theme() if mode == 'system' else mode


def save_theme(theme):
    path = appearance_path()
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(json.dumps({'theme':theme}).encode())
    try:
        os.replace(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)


def apply_theme(root, theme):
    dark = theme == 'dark'
    bg, fg, field, select = ('#242830','#ecedf0','#171b22','#395c8e') if dark else ('#f4f5f7','#20242a','#ffffff','#c5d8f0')
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.',background=bg,foreground=fg,fieldbackground=field)
    style.configure('TEntry',fieldbackground=field,foreground=fg,insertcolor=fg)
    style.configure('TCombobox',fieldbackground=field,foreground=fg,arrowcolor=fg)
    style.map('TCombobox',fieldbackground=[('readonly',field)],foreground=[('readonly',fg)])
    for widget in ('TButton','TCheckbutton','TCombobox'):
        style.map(widget,background=[('active',select)],foreground=[('disabled','#858994')])
    root.configure(background=bg)
    root.option_add('*TCombobox*Listbox.background',field)
    root.option_add('*TCombobox*Listbox.foreground',fg)
    root.option_add('*TCombobox*Listbox.selectBackground',select)
    def visit(parent):
        for child in parent.winfo_children():
            if child.winfo_class() == 'Text':
                child.configure(background=field,foreground=fg,insertbackground=fg,selectbackground=select)
            elif child.winfo_class() == 'Frame':
                child.configure(background=bg)
            visit(child)
    visit(root)
