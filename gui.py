"""Tkinter-интерфейс для загрузчика YouTube (yt-dlp)."""

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from core import Downloader, find_ffmpeg, is_playlist

DEFAULT_DIR = Path("downloads")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("YT Downloader")
        self.minsize(560, 420)

        self.queue: "queue.Queue[tuple]" = queue.Queue()
        self.dl: Downloader | None = None

        self._build_ui()
        if not find_ffmpeg():
            self._log("warning", "ffmpeg не найден: слияние/субтитры/метаданные будут недоступны.")
        else:
            self._log("info", "ffmpeg найден — слияние и встраивание включены.")

        self.after(100, self._drain)

    # -- построение интерфейса ----------------------------------------------
    def _build_ui(self) -> None:
        pad = {"padx": 8, "pady": 4}

        frame = ttk.Frame(self, padding=10)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Ссылка (видео/плейлист):").grid(row=0, column=0, sticky="w", **pad)
        self.url_var = tk.StringVar()
        self.url_entry = ttk.Entry(frame, textvariable=self.url_var)
        self.url_entry.grid(row=0, column=1, columnspan=2, sticky="ew", **pad)

        ttk.Label(frame, text="Папка скачивания:").grid(row=1, column=0, sticky="w", **pad)
        self.path_var = tk.StringVar(value=str(DEFAULT_DIR.resolve()))
        self.path_entry = ttk.Entry(frame, textvariable=self.path_var)
        self.path_entry.grid(row=1, column=1, sticky="ew", **pad)
        self.browse_btn = ttk.Button(frame, text="Обзор…", command=self._browse)
        self.browse_btn.grid(row=1, column=2, sticky="ew", **pad)

        self.playlist_var = tk.BooleanVar()
        self.playlist_check = ttk.Checkbutton(
            frame, text="Скачать весь плейлист (иначе только одно видео)", variable=self.playlist_var
        )
        self.playlist_check.grid(row=2, column=0, columnspan=3, sticky="w", **pad)

        buttons = ttk.Frame(frame)
        buttons.grid(row=3, column=0, columnspan=3, sticky="we", **pad)
        self.download_btn = ttk.Button(buttons, text="Скачать", command=self._start)
        self.download_btn.pack(side="left")
        self.cancel_btn = ttk.Button(buttons, text="Отмена", command=self._cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=(8, 0))

        self.pb = ttk.Progressbar(frame, maximum=100)
        self.pb.grid(row=4, column=0, columnspan=3, sticky="ew", **pad)

        self.status_var = tk.StringVar(value="Готов.")
        ttk.Label(frame, textvariable=self.status_var).grid(row=5, column=0, columnspan=3, sticky="w", **pad)

        self.log = scrolledtext.ScrolledText(frame, height=14, state="disabled")
        self.log.grid(row=6, column=0, columnspan=3, sticky="nsew", **pad)
        frame.rowconfigure(6, weight=1)

    # -- обработчики UI ------------------------------------------------------
    def _browse(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.path_var.get() or DEFAULT_DIR)
        if chosen:
            self.path_var.set(chosen)

    def _start(self) -> None:
        url = self.url_var.get().strip()
        dest = self.path_var.get().strip() or str(DEFAULT_DIR)
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
            target=self.dl.download, args=(url, dest, playlist), daemon=True, name="yt-dlp"
        ).start()

    def _cancel(self) -> None:
        if self.dl:
            self.dl.stop()
            self._log("warning", "Запрос остановки…")

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for w in (self.url_entry, self.path_entry, self.browse_btn,
                  self.playlist_check, self.download_btn):
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
        with open("selftest.log", "w", encoding="utf-8") as f:
            dl = Downloader(on_log=lambda lvl, msg: f.write(f"[{lvl}] {msg}\n"))
            dl.download(url, dest)
        print("selftest done")
        sys.exit(0)

    App().mainloop()