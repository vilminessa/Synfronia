"""Tkinter-интерфейс для загрузчика YouTube (yt-dlp)."""

import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from core import (
    DEFAULT_SETTINGS,
    QUALITY_FORMATS,
    SUBTITLE_OPTIONS,
    THEMES,
    Downloader,
    base_dir,
    default_download_dir,
    find_ffmpeg,
    is_playlist,
    load_settings,
    save_settings,
)

SUBTITLE_LABELS = {"off": "Выкл", "ru": "Русские", "en": "Английские", "all": "Все"}
QUALITY_LABELS = {"lossless": "Lossless (максимум)", "1080": "1080p", "720": "720p", "240": "240p"}


class SettingsDialog(tk.Toplevel):
    """Настройки: пока только выбор цветовой темы."""

    def __init__(self, master: "App"):
        super().__init__(master)
        self.master = master
        self.title("Настройки")
        self.transient(master)
        self.resizable(False, False)

        self._keys = list(THEMES)
        self._original = master.settings["theme"]

        ttk.Label(self, text="Цветовая тема:").grid(row=0, column=0, padx=10, pady=(10, 4), sticky="w")
        labels = [THEMES[k]["label"] for k in self._keys]
        self.combo = ttk.Combobox(self, values=labels, state="readonly", width=30)
        self.combo.grid(row=0, column=1, padx=(0, 10), pady=(10, 4))
        self.combo.current(self._keys.index(master.settings["theme"]))
        self.combo.bind("<<ComboboxSelected>>", self._preview)

        btns = ttk.Frame(self)
        btns.grid(row=1, column=0, columnspan=2, pady=10)
        ttk.Button(btns, text="OK", command=self._ok).pack(side="left", padx=4)
        ttk.Button(btns, text="Отмена", command=self._cancel).pack(side="left", padx=4)

        self.grab_set()

    def _preview(self, _event=None) -> None:
        self.master.apply_theme(self._keys[self.combo.current()])

    def _ok(self) -> None:
        key = self._keys[self.combo.current()]
        self.master.apply_theme(key)
        self.master.settings["theme"] = key
        self.master._save_settings()
        self.destroy()

    def _cancel(self) -> None:
        self.master.apply_theme(self._original)
        self.destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Synfronia")
        self.minsize(640, 460)

        self.settings = load_settings()
        self.queue: "queue.Queue[tuple]" = queue.Queue()
        self.dl: Downloader | None = None

        self._build_ui()
        self.apply_theme(self.settings["theme"])

        if not find_ffmpeg():
            self._log("warning", "ffmpeg не найден: слияние/субтитры/метаданные будут недоступны.")
        else:
            self._log("info", "ffmpeg найден — слияние и встраивание включены.")

        self.after(100, self._drain)

    # -- построение интерфейса ----------------------------------------------
    def _build_ui(self) -> None:
        pad = {"padx": 8, "pady": 4}

        frame = ttk.Frame(self, padding=8)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Ссылка (видео/плейлист):").grid(row=0, column=0, sticky="w", **pad)
        self.url_var = tk.StringVar()
        self.url_entry = ttk.Entry(frame, textvariable=self.url_var)
        self.url_entry.grid(row=0, column=1, columnspan=2, sticky="ew", **pad)

        ttk.Label(frame, text="Папка скачивания:").grid(row=1, column=0, sticky="w", **pad)
        self.path_var = tk.StringVar(value=str(default_download_dir()))
        self.path_entry = ttk.Entry(frame, textvariable=self.path_var)
        self.path_entry.grid(row=1, column=1, sticky="ew", **pad)
        self.browse_btn = ttk.Button(frame, text="Обзор…", command=self._browse)
        self.browse_btn.grid(row=1, column=2, sticky="ew", **pad)

        self.playlist_var = tk.BooleanVar()
        self.playlist_check = ttk.Checkbutton(
            frame, text="Скачать весь плейлист (иначе только одно видео)", variable=self.playlist_var
        )
        self.playlist_check.grid(row=2, column=0, columnspan=3, sticky="w", **pad)

        self.group_var = tk.BooleanVar(value=bool(self.settings.get("group_playlist", True)))
        self.group_check = ttk.Checkbutton(
            frame, text="Сгруппировать: плейлист в подпапку с его названием", variable=self.group_var
        )
        self.group_check.grid(row=3, column=0, columnspan=3, sticky="w", **pad)
        self.group_var.trace_add("write", lambda *_: self._on_group_change())

        opts_row = ttk.Frame(frame)
        opts_row.grid(row=4, column=0, columnspan=3, sticky="w", **pad)

        ttk.Label(opts_row, text="Субтитры:").pack(side="left")
        self.subtitles_combo = ttk.Combobox(
            opts_row, state="readonly", width=12, values=list(SUBTITLE_LABELS.values())
        )
        self.subtitles_combo.pack(side="left", padx=(4, 12))
        self.subtitles_combo.bind("<<ComboboxSelected>>", lambda *_: self._on_subtitles_change())

        ttk.Label(opts_row, text="Качество:").pack(side="left")
        self.quality_combo = ttk.Combobox(
            opts_row, state="readonly", width=18, values=list(QUALITY_LABELS.values())
        )
        self.quality_combo.pack(side="left", padx=(4, 12))
        self.quality_combo.bind("<<ComboboxSelected>>", lambda *_: self._on_quality_change())

        self.hevc_var = tk.BooleanVar(value=bool(self.settings.get("hevc", False)))
        self.hevc_check = ttk.Checkbutton(opts_row, text="Конвертировать в HEVC (H.265)", variable=self.hevc_var)
        self.hevc_check.pack(side="left")
        self.hevc_var.trace_add("write", lambda *_: self._on_hevc_change())

        buttons = ttk.Frame(frame)
        buttons.grid(row=5, column=0, columnspan=3, sticky="we", **pad)
        ttk.Button(buttons, text="Настройки…", command=self._open_settings).pack(side="left")
        self.download_btn = ttk.Button(buttons, text="Скачать", command=self._start)
        self.download_btn.pack(side="left", padx=(8, 0))
        self.cancel_btn = ttk.Button(buttons, text="Отмена", command=self._cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=(8, 0))

        self.pb = ttk.Progressbar(frame, maximum=100)
        self.pb.grid(row=6, column=0, columnspan=3, sticky="ew", **pad)

        self.status_var = tk.StringVar(value="Готов.")
        ttk.Label(frame, textvariable=self.status_var).grid(row=7, column=0, columnspan=3, sticky="w", **pad)

        self.log = scrolledtext.ScrolledText(frame, height=14, state="disabled")
        self.log.grid(row=8, column=0, columnspan=3, sticky="nsew", **pad)
        frame.rowconfigure(8, weight=1)

        self._restore_settings()

    def _restore_settings(self) -> None:
        subs = SUBTITLE_LABELS.get(self.settings.get("subtitles", "ru"), "Русские")
        self.subtitles_combo.set(subs)
        qual = QUALITY_LABELS.get(self.settings.get("quality", "lossless"), "Lossless (максимум)")
        self.quality_combo.set(qual)

    # -- сохранение настроек -------------------------------------------------
    def _save_settings(self) -> None:
        try:
            save_settings(self.settings)
        except OSError as exc:
            messagebox.showerror("Ошибка", f"Не удалось сохранить настройки:\n{exc}")

    def _on_group_change(self) -> None:
        self.settings["group_playlist"] = bool(self.group_var.get())
        self._save_settings()

    def _on_subtitles_change(self) -> None:
        label = self.subtitles_combo.get()
        key = next((k for k, v in SUBTITLE_LABELS.items() if v == label), "ru")
        self.settings["subtitles"] = key
        self._save_settings()

    def _on_quality_change(self) -> None:
        label = self.quality_combo.get()
        key = next((k for k, v in QUALITY_LABELS.items() if v == label), "lossless")
        self.settings["quality"] = key
        self._save_settings()

    def _on_hevc_change(self) -> None:
        self.settings["hevc"] = bool(self.hevc_var.get())
        self._save_settings()

    def _open_settings(self) -> None:
        SettingsDialog(self)

    # -- темы ----------------------------------------------------------------
    def apply_theme(self, key: str) -> None:
        colors = THEMES.get(key) or THEMES["scary_forest"]
        style = ttk.Style(self)
        style.theme_use("clam")

        bg, surface, widget = colors["bg"], colors["surface"], colors["widget"]
        text, accent = colors["text"], colors["accent"]

        self.configure(background=bg)
        style.configure(".", background=bg, foreground=text)
        style.configure("TFrame", background=bg)
        style.configure("TLabel", background=bg, foreground=text)
        style.configure("TCheckbutton", background=bg, foreground=text)
        style.map("TCheckbutton", background=[("active", bg)])
        style.configure("TButton", background=surface, foreground=text, bordercolor=surface)
        style.map(
            "TButton",
            background=[("active", accent), ("pressed", accent)],
            foreground=[("active", bg), ("pressed", bg)],
        )
        style.configure(
            "TEntry",
            fieldbackground=widget,
            foreground=text,
            insertcolor=text,
            bordercolor=surface,
        )
        style.configure(
            "TCombobox",
            fieldbackground=widget,
            background=widget,
            foreground=text,
            arrowcolor=accent,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", widget)],
            foreground=[("readonly", text)],
            selectbackground=[("readonly", accent)],
            selectforeground=[("readonly", bg)],
        )
        style.configure(
            "Horizontal.TProgressbar",
            troughcolor=surface,
            background=accent,
            bordercolor=surface,
            lightcolor=accent,
            darkcolor=accent,
        )
        self.option_add("*TCombobox*Listbox.background", widget)
        self.option_add("*TCombobox*Listbox.foreground", text)
        self.option_add("*TCombobox*Listbox.selectBackground", accent)
        self.option_add("*TCombobox*Listbox.selectForeground", bg)

        self.log.configure(
            bg=widget,
            fg=text,
            insertbackground=text,
            highlightbackground=surface,
            highlightcolor=accent,
        )
        self.status_var.set(self.status_var.get())

    # -- обработчики UI ------------------------------------------------------
    def _browse(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.path_var.get() or str(default_download_dir()))
        if chosen:
            self.path_var.set(chosen)

    def _start(self) -> None:
        url = self.url_var.get().strip()
        dest = self.path_var.get().strip() or str(default_download_dir())
        playlist = self.playlist_var.get()

        if not url:
            messagebox.showwarning("Пустая ссылка", "Введите ссылку на видео или плейлист.")
            return
        if not playlist and is_playlist(url):
            self._log("info", "Ссылка на плейлист без флажка — скачается только одно видео.")

        self._set_busy(True)
        self.pb["value"] = 0
        self.status_var.set("Запуск…")
        self.dl = Downloader(
            on_log=lambda lvl, msg: self.queue.put(("log", lvl, msg)),
            on_progress=lambda d: self.queue.put(("progress", d)),
        )
        threading.Thread(
            target=lambda: self.dl.download(
                url,
                dest,
                playlist=playlist,
                group=bool(self.group_var.get()),
                subtitles=self.settings["subtitles"],
                quality=self.settings["quality"],
                hevc=bool(self.hevc_var.get()),
            ),
            daemon=True,
            name="yt-dlp",
        ).start()

    def _cancel(self) -> None:
        if self.dl:
            self.dl.stop()
            self._log("warning", "Запрос остановки…")

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for w in (self.url_entry, self.path_entry, self.browse_btn,
                  self.playlist_check, self.group_check,
                  self.subtitles_combo, self.quality_combo, self.hevc_check,
                  self.download_btn):
            w.configure(state=state)
        self.cancel_btn.configure(state="normal" if busy else "disabled")

    # -- поток -> UI ---------------------------------------------------------
    def _drain(self) -> None:
        try:
            while True:
                kind, *payload = self.queue.get_nowait()
                if kind == "log":
                    self._log(*payload)
                elif kind == "progress":
                    self._on_progress(payload[0])
        except queue.Empty:
            pass
        self.after(100, self._drain)

    def _on_progress(self, d: dict) -> None:
        status = d.get("status")
        if status == "downloading":
            percent = d.get("percent")
            if percent is None:
                self.pb.config(mode="indeterminate")
                self.pb.start(12)
            else:
                self.pb.stop()
                self.pb.config(mode="determinate", value=percent)
            name = d.get("filename") or ""
            speed = d.get("speed")
            eta = d.get("eta")
            bits = f"{percent:.0f}%" if percent is not None else "…"
            spd = f"{speed / 1024 / 1024:.1f} МБ/с" if speed else ""
            eta_s = f" ETA {int(eta)}с" if eta else ""
            self.status_var.set(f"{name} — {bits}{spd and ' | ' + spd}{eta_s}")
        elif status == "postprocessing":
            self.pb.config(mode="indeterminate")
            self.pb.start(12)
            self.status_var.set(d.get("msg", "Постобработка…"))
        elif status == "done":
            self.pb.stop()
            self.pb.config(mode="determinate")
            self._set_busy(False)
            self.status_var.set("Готов.")

    # -- лог -----------------------------------------------------------------
    def _log(self, level: str, msg: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", f"{msg}\n")
        self.log.configure(state="disabled")
        self.log.see("end")


if __name__ == "__main__":
    import sys

    if "--selftest" in sys.argv:
        from core import Downloader

        dest = sys.argv[2] if len(sys.argv) > 2 else "downloads_selftest"
        url = sys.argv[3] if len(sys.argv) > 3 else "https://youtu.be/GUS0q7gZdNE"
        subtitles = "ru"
        quality = "lossless"
        hevc = False
        for opt in sys.argv[4:]:
            if opt.startswith("--subtitles="):
                subtitles = opt.split("=", 1)[1]
            elif opt.startswith("--quality="):
                quality = opt.split("=", 1)[1]
            elif opt == "--hevc":
                hevc = True
        with open(base_dir() / "selftest.log", "w", encoding="utf-8") as f:
            dl = Downloader(on_log=lambda lvl, msg: f.write(f"[{lvl}] {msg}\n"))
            dl.download(url, dest, subtitles=subtitles, quality=quality, hevc=hevc)
        print("selftest done")
        sys.exit(0)

    App().mainloop()