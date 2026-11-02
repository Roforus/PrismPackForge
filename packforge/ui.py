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
        from .appearance import load_theme_mode, system_theme
        self.root = tk.Tk()
        self.root.title(title)
        self.root.geometry("820x670")
        self.root.minsize(720, 600)
        self.theme_mode = load_theme_mode()
        self.theme = system_theme() if self.theme_mode == 'system' else self.theme_mode
        topbar = ttk.Frame(self.root, padding=(10,4))
        topbar.pack(fill='x')
        self.topbar = topbar
        self.theme_button = ttk.Button(topbar,text='☾',width=3,command=self.toggle_theme)
        self.theme_button.pack(side='right')
        self.frame = ttk.Frame(self.root, padding=20)
        self.frame.pack(fill="both", expand=True)
        self.frame.columnconfigure(1, weight=1)
        self.events = queue.Queue()
        self.busy = False
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after_idle(self.apply_appearance)
        self.root.after(2000,self.poll_system_theme)

    def apply_appearance(self):
        from .appearance import apply_theme
        apply_theme(self.root,self.theme)
        self.theme_button.configure(text='☀' if self.theme == 'dark' else '☾')

    def poll_system_theme(self):
        from .appearance import system_theme
        if self.theme_mode == 'system':
            theme = system_theme()
            if theme != self.theme:
                self.theme = theme
                self.apply_appearance()
        self.root.after(2000,self.poll_system_theme)

    def set_theme_mode(self,mode):
        from .appearance import save_theme, system_theme
        self.theme_mode = mode
        self.theme = system_theme() if mode == 'system' else mode
        self.apply_appearance()
        try:
            save_theme(mode)
        except OSError:
            pass

    def toggle_theme(self):
        self.set_theme_mode('dark' if self.theme == 'light' else 'light')

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

    def run_task(self, fn, on_success=None):
        if self.busy:
            return
        self.busy = True
        self.button.configure(state="disabled")
        self.progress.start()

        def worker():
            try:
                fn(lambda text: self.events.put(("log", str(text))))
                if on_success:
                    self.events.put(('success_callback',on_success))
                self.events.put(("done", "Готово"))
            except Exception as exc:
                self.events.put(("error", str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        while not self.events.empty():
            kind, text = self.events.get_nowait()
            if kind == 'success_callback':
                text()
                continue
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
    from .export_ui import ExporterUI
    ExporterUI().window.root.mainloop()
