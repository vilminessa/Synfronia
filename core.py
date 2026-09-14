"""Библиотека загрузки: обвязка над yt-dlp с логом, прогрессом и остановкой."""

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from yt_dlp import YoutubeDL
from yt_dlp.postprocessor.embedthumbnail import EmbedThumbnailPP
from yt_dlp.postprocessor.ffmpeg import (
    FFmpegMetadataPP,
    FFmpegPostProcessor,
    FFmpegPostProcessorError,
    FFmpegEmbedSubtitlePP,
)

_PLAYLIST_RE = re.compile(r"[?&]list=")

# -- темы --------------------------------------------------------------------
# Поля темы: label (название), цвета палитры bg/surface/widget/text/accent/warn,
# opacity (общая прозрачность интерфейса 0..1), радиусы скругления
# radius_s / radius_m / radius_l (px), hidden (скрыть из списка).
# Значения — дефолты; пользователь правит копии в
# %LOCALAPPDATA%\Synfronia\themes\{имя_темы}\theme.json.
_THEME_DEFAULTS = {
    "warn": "#ffb454",
    "opacity": 1.0,
    "radius_s": 6,
    "radius_m": 8,
    "radius_l": 12,
}
THEMES = {
    "scary_forest": {
        "label": "Scary Forest",
        "bg": "#0c1622",
        "surface": "#1f2b29",
        "widget": "#23444b",
        "text": "#dcdedd",
        "accent": "#628d7c",
        **_THEME_DEFAULTS,
    },
    "technology_day": {
        "label": "Technology day",
        "bg": "#00181a",
        "surface": "#00585a",
        "widget": "#003638",
        "text": "#dcdedd",
        "accent": "#00989b",
        **_THEME_DEFAULTS,
    },
    "technology_pinks": {
        "label": "Technology Pinks",
        "bg": "#ffebec",
        "surface": "#ffcbe2",
        "widget": "#ffffff",
        "text": "#5d2547",
        "accent": "#c15f9b",
        **_THEME_DEFAULTS,
    },
    "scarred_mind": {
        "label": "Scarred Mind",
        "bg": "#252b47",
        "surface": "#2f3b65",
        "widget": "#1e2542",
        "text": "#b9c2d6",
        "accent": "#f1b970",
        **_THEME_DEFAULTS,
    },
    "audrey_main": {
        "label": "Audrey Main Colours",
        "bg": "#fff5f0",
        "surface": "#f9f9f9",
        "widget": "#ededed",
        "text": "#5d5d5d",
        "accent": "#96af9b",
        **_THEME_DEFAULTS,
    },
    "night_sky": {
        "label": "Basic Night Sky",
        "bg": "#373051",
        "surface": "#3b2f4d",
        "widget": "#323756",
        "text": "#fffedd",
        "accent": "#fff2c9",
        **_THEME_DEFAULTS,
    },
    "vilmy": {
        "label": "Vilmy~",
        "bg": "#F5F0E6",
        "surface": "#EFE9DC",
        "widget": "#EDE5D3",
        "text": "#1F3A2E",
        "accent": "#B89968",
        **_THEME_DEFAULTS,
    },
}

DEFAULT_SETTINGS = {
    "theme": "scarred_mind",
    "subtitles": "en",       # off / ru / en / all
    "quality": "lossless",   # lossless / 8k / 4k / 2k / 1080 / 720 / 480 / 240
    "retries": 10,           # количество повторов при сетевых ошибках (yt-dlp)
    "socket_timeout": 20,    # таймаут сокета в секундах (yt-dlp)
    "transcode": "none",     # none / libx265 / nvenc / amf / qsv
    "group_playlist": True,
    "language": "ru",
}


def based_settings() -> dict:
    """Дефолтные настройки из based_settings.json (приоритет: рядом с exe -> рядом
    с кодом -> встроенные). Пользовательские ключи в файле переопределяют дефолты."""
    base = dict(DEFAULT_SETTINGS)
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(base_dir() / "based_settings.json")
    candidates.append(Path(__file__).resolve().parent / "based_settings.json")
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            for key in DEFAULT_SETTINGS:
                if key in data:
                    base[key] = data[key]
            break
    return base

LANGUAGES = ("ru", "en", "ja", "zh-CN", "es", "de")

# Самоназвания языков (не переводим — это «название языка на самом языке»);
# используются как thisLang при генерации базовых файлов переводов.
SELF_NAMES: dict[str, str] = {
    "ru": "Русский",
    "en": "English",
    "ja": "日本語",
    "zh-CN": "简体中文",
    "es": "Español",
    "de": "Deutsch",
}

I18N = {
    "ru": {
        "ui.sub": "Скачивание видео и плейлистов YouTube (yt-dlp)",
        "ui.settings": "Настройки",
        "ui.close": "Закрыть",
        "tab.video": "Видео",
        "tab.playlist": "Плейлист",
        "url.video.label": "Ссылка на видео:",
        "url.playlist.label": "Ссылка на плейлист:",
        "group.label": "Сгруппировать: плейлист в подпапку с его названием",
        "warn.ffmpeg": "ffmpeg не найден — слияние, субтитры, метаданные и перекодировка будут недоступны.",
        "ffmpeg.overlay_title": "Установить FFmpeg",
        "ffmpeg.overlay_hint": "Для слияния видео и аудио, субтитров, метаданных и перекодировки нужен ffmpeg.",
        "ffmpeg.download": "Загрузить FFmpeg",
        "ffmpeg.downloading": "Загружаю ffmpeg… {pct}%",
        "ffmpeg.extracting": "Распаковываю ffmpeg…",
        "ffmpeg.ready": "ffmpeg установлен.",
        "ffmpeg.error": "Не удалось скачать ffmpeg: {exc}",
        "btn.download": "Скачать",
        "btn.stop": "Отмена",
        "status.ready": "Готов.",
        "status.enter.video": "Введите ссылку на видео.",
        "status.enter.playlist": "Введите ссылку на плейлист.",
        "status.playlist.warning": "Это ссылка на плейлист: во вкладке «Видео» скачается только само видео. Откройте вкладку «Плейлист», чтобы скачать всё.",
        "sheet.tab.ui": "Интерфейс",
        "sheet.tab.dl": "Загрузчик",
        "sheet.dest.label": "Папка скачивания:",
        "sheet.browse": "Обзор…",
        "sheet.theme.label": "Тема:",
        "sheet.subs.label": "Субтитры:",
        "sheet.qual.label": "Ограничение качества:",
        "sheet.transcode.label": "Перекодировка:",
        "sheet.network.label": "Сеть",
        "sheet.retries.label": "Повторы:",
        "sheet.timeout.label": "Таймаут (сек.):",
        "sheet.lang.label": "Язык:",
        "subs.off": "Выкл",
        "subs.ru": "Русские",
        "subs.en": "Английские",
        "subs.all": "Все",
        "qual.lossless": "Lossless (максимум)",
        "trans.none": "По умолчанию (Нет)",
        "trans.libx265": "HEVC (x265, программный)",
        "trans.nvenc": "NVIDIA NVENC (H.265)",
        "trans.amf": "AMD AMF (H.265)",
        "trans.qsv": "Intel Quick Sync (QSV) (H.265)",
        "trans.unavailable": "(недоступно)",
        "trans.note.noffmpeg": "ffmpeg не найден — перекодировка недоступна.",
        "trans.note.missing": "В вашей сборке ffmpeg недоступны: ",
        "theme_scary_forest": "Scary Forest",
        "theme_technology_day": "Technology day",
        "theme_technology_pinks": "Technology Pinks",
        "theme_scarred_mind": "Scarred Mind",
        "theme_audrey_main": "Audrey Main Colours",
        "theme_night_sky": "Basic Night Sky",
        "theme_vilmy": "Vilmy~",
        "clicker.title": "…",
        "clicker.hint": "Кликни меня~",
        "clicker.messages": [
            "Закликай меня до смерти~~~",
            "Ещё, ещё, не останавливайся~",
            "Я так близко… ещё чуть-чуть~",
            "С каждым кликом я та-аю~",
            "Ты что, хочешь докликать меня до… ну ты понял~",
            "Слышишь, как я щёлкаю от удовольствия~",
        ],
        "p.retry_hls": "Не удалось: пробую HLS-поток ({n})…",
        "p.done_errors": "Готово с ошибками — часть файлов не скачалась.",
        "p.ready": "Готов.",
        "p.start": "Запуск…",
        "p.enter_url": "Введите ссылку на видео или плейлист.",
        "p.playlist_warn": "Это ссылка на плейлист во вкладке «Видео» — скачается только одно видео. Для всего плейлиста используйте вкладку «Плейлист».",
        "p.stop_req": "Запрос остановки…",
        "p.going": "идёт загрузка…",
        "p.mbps": "МБ/с",
        "p.eta_prefix": "ETA",
        "p.eta_sec": "с",
        "p.post": "Постобработка…",
        "p.mode": "Режим: {mode} (группировка {group})",
        "p.mode.video": "одно видео",
        "p.mode.playlist": "плейлист",
        "p.mode.on": "вкл",
        "p.mode.off": "выкл",
        "p.transcoding": "Перекодирование: {label}.",
        "p.done.playlist": "Готово: {n} видео -> {dest}",
        "p.done.single": "Готово: {title}",
        "p.cancelled": "Загрузка отменена пользователем.",
        "p.error": "Ошибка: {exc}",
        "p.ffmpeg_missing": "ffmpeg не найден: слияние/субтитры/метаданные будут недоступны.",
        "p.skip_not_mp4": "Пропуск перекодировки: файл не в mp4.",
        "p.transcode_run": "Перекодировка ({vcodec})...",
        "p.postprocess": "Постобработка (ffmpeg: слияние/HEVC/метаданные/субтитры/обложка)...",
    },
    "en": {
        "ui.sub": "Download YouTube videos and playlists (yt-dlp)",
        "ui.settings": "Settings",
        "ui.close": "Close",
        "tab.video": "Video",
        "tab.playlist": "Playlist",
        "url.video.label": "Video link:",
        "url.playlist.label": "Playlist link:",
        "group.label": "Group: save playlist into a subfolder named after it",
        "warn.ffmpeg": "ffmpeg not found — merging, subtitles, metadata and transcoding will be unavailable.",
        "ffmpeg.overlay_title": "Install FFmpeg",
        "ffmpeg.overlay_hint": "ffmpeg is required for merging video+audio, subtitles, metadata and transcoding.",
        "ffmpeg.download": "Download FFmpeg",
        "ffmpeg.downloading": "Downloading ffmpeg… {pct}%",
        "ffmpeg.extracting": "Extracting ffmpeg…",
        "ffmpeg.ready": "ffmpeg installed.",
        "ffmpeg.error": "Failed to download ffmpeg: {exc}",
        "btn.download": "Download",
        "btn.stop": "Cancel",
        "status.ready": "Ready.",
        "status.enter.video": "Enter a video link.",
        "status.enter.playlist": "Enter a playlist link.",
        "status.playlist.warning": "This is a playlist link: in the Video tab only the single video will be downloaded. Open the Playlist tab to download everything.",
        "sheet.tab.ui": "Interface",
        "sheet.tab.dl": "Downloader",
        "sheet.dest.label": "Download folder:",
        "sheet.browse": "Browse…",
        "sheet.theme.label": "Theme:",
        "sheet.subs.label": "Subtitles:",
        "sheet.qual.label": "Quality limit:",
        "sheet.transcode.label": "Transcoding:",
        "sheet.network.label": "Network",
        "sheet.retries.label": "Retries:",
        "sheet.timeout.label": "Timeout (sec):",
        "sheet.lang.label": "Language:",
        "subs.off": "Off",
        "subs.ru": "Russian",
        "subs.en": "English",
        "subs.all": "All",
        "qual.lossless": "Lossless (max)",
        "trans.none": "Default (None)",
        "trans.libx265": "HEVC (x265, software)",
        "trans.nvenc": "NVIDIA NVENC (H.265)",
        "trans.amf": "AMD AMF (H.265)",
        "trans.qsv": "Intel Quick Sync (QSV) (H.265)",
        "trans.unavailable": "(unavailable)",
        "trans.note.noffmpeg": "ffmpeg not found — transcoding is unavailable.",
        "trans.note.missing": "Not available in your ffmpeg build: ",
        "theme_scary_forest": "Scary Forest",
        "theme_technology_day": "Technology Day",
        "theme_technology_pinks": "Technology Pinks",
        "theme_scarred_mind": "Scarred Mind",
        "theme_audrey_main": "Audrey Main Colours",
        "theme_night_sky": "Basic Night Sky",
        "theme_vilmy": "Vilmy~",
        "clicker.title": "…",
        "clicker.hint": "Click me~",
        "clicker.messages": [
            "Click me to death~~~",
            "More, more, don't stop~",
            "I'm so close… just a little more~",
            "Every click melts me~",
            "You're gonna click me into… well, you know~",
            "Hear how I click with pleasure~",
        ],
        "p.retry_hls": "Failed: trying HLS stream ({n})…",
        "p.done_errors": "Done with errors - some files were not downloaded.",
        "p.ready": "Ready.",
        "p.start": "Starting…",
        "p.enter_url": "Enter a video or playlist link.",
        "p.playlist_warn": "This is a playlist link opened in the Video tab — only the single video will be downloaded. Use the Playlist tab to download everything.",
        "p.stop_req": "Stop requested…",
        "p.going": "downloading…",
        "p.mbps": "MB/s",
        "p.eta_prefix": "ETA",
        "p.eta_sec": "s",
        "p.post": "Post-processing…",
        "p.mode": "Mode: {mode} (grouping {group})",
        "p.mode.video": "single video",
        "p.mode.playlist": "playlist",
        "p.mode.on": "on",
        "p.mode.off": "off",
        "p.transcoding": "Transcoding: {label}.",
        "p.done.playlist": "Done: {n} videos -> {dest}",
        "p.done.single": "Done: {title}",
        "p.cancelled": "Download cancelled by the user.",
        "p.error": "Error: {exc}",
        "p.ffmpeg_missing": "ffmpeg not found: merging/subtitles/metadata will be unavailable.",
        "p.skip_not_mp4": "Skipping transcode: file is not mp4.",
        "p.transcode_run": "Transcoding ({vcodec})...",
        "p.postprocess": "Post-processing (ffmpeg: merge/HEVC/metadata/subtitles/thumbnail)...",
    },
    "ja": {
        "ui.sub": "YouTubeの動画とプレイリストをダウンロード（yt-dlp）",
        "ui.settings": "設定",
        "ui.close": "閉じる",
        "tab.video": "動画",
        "tab.playlist": "プレイリスト",
        "url.video.label": "動画のURL:",
        "url.playlist.label": "プレイリストのURL:",
        "group.label": "グループ化: プレイリストを名前の付いたサブフォルダーに保存",
        "warn.ffmpeg": "ffmpegが見つかりません — 結合・字幕・メタデータ・再エンコードは利用できません。",
        "ffmpeg.overlay_title": "FFmpegをインストール",
        "ffmpeg.overlay_hint": "動画と音声の結合、字幕、メタデータ、再エンコードにはffmpegが必要です。",
        "ffmpeg.download": "FFmpegをダウンロード",
        "ffmpeg.downloading": "ffmpegをダウンロード中… {pct}%",
        "ffmpeg.extracting": "ffmpegを展開中…",
        "ffmpeg.ready": "ffmpegをインストールしました。",
        "ffmpeg.error": "ffmpegのダウンロードに失敗: {exc}",
        "btn.download": "ダウンロード",
        "btn.stop": "キャンセル",
        "status.ready": "準備完了。",
        "status.enter.video": "動画のURLを入力してください。",
        "status.enter.playlist": "プレイリストのURLを入力してください。",
        "status.playlist.warning": "これはプレイリストのURLです: 「動画」タブでは単一の動画のみダウンロードされます。「プレイリスト」タブを開くとすべてダウンロードされます。",
        "sheet.tab.ui": "インターフェース",
        "sheet.tab.dl": "ダウンローダー",
        "sheet.dest.label": "ダウンロード先:",
        "sheet.browse": "参照…",
        "sheet.theme.label": "テーマ:",
        "sheet.subs.label": "字幕:",
        "sheet.qual.label": "画質制限:",
        "sheet.transcode.label": "再エンコード:",
        "sheet.network.label": "ネットワーク",
        "sheet.retries.label": "リトライ回数:",
        "sheet.timeout.label": "タイムアウト（秒）:",
        "sheet.lang.label": "言語:",
        "subs.off": "なし",
        "subs.ru": "ロシア語",
        "subs.en": "英語",
        "subs.all": "すべて",
        "qual.lossless": "ロスレス（最高）",
        "trans.none": "デフォルト（なし）",
        "trans.libx265": "HEVC（x265・ソフトウェア）",
        "trans.nvenc": "NVIDIA NVENC（H.265）",
        "trans.amf": "AMD AMF（H.265）",
        "trans.qsv": "Intel Quick Sync（QSV）（H.265）",
        "trans.unavailable": "（利用不可）",
        "trans.note.noffmpeg": "ffmpegが見つかりません — 再エンコードは利用できません。",
        "trans.note.missing": "このffmpegビルドでは利用不可: ",
        "theme_scary_forest": "暗い森",
        "theme_technology_day": "テクノロジーデー",
        "theme_technology_pinks": "テクノロジーピンク",
        "theme_scarred_mind": "傷跡の心",
        "theme_audrey_main": "オードリー・メイン・カラーズ",
        "theme_night_sky": "夜空",
        "theme_vilmy": "Vilmy~",
        "clicker.title": "…",
        "clicker.hint": "クリックしてね~",
        "clicker.messages": [
            "死ぬまでクリックして~~~",
            "もっと、もっと、止めないで~",
            "もうすぐ…あともう少し~",
            "クリックのたびに溶けちゃう~",
            "クリックしすぎて…もう、わかってるでしょ~",
            "聞こえる？気持ちよく弾けてる音~",
        ],
        "p.retry_hls": "失敗: HLSストリームを試します ({n})…",
        "p.done_errors": "エラーありで終了 — 一部のファイルはダウンロードされませんでした。",
        "p.ready": "準備完了。",
        "p.start": "開始中…",
        "p.enter_url": "動画またはプレイリストのURLを入力してください。",
        "p.playlist_warn": "「動画」タブで開かれたプレイリストのURLです — 単一の動画のみダウンロードされます。すべてをダウンロードするには「プレイリスト」タブを使用してください。",
        "p.stop_req": "停止を要求しました…",
        "p.going": "ダウンロード中…",
        "p.mbps": "MB/秒",
        "p.eta_prefix": "残り",
        "p.eta_sec": "秒",
        "p.post": "後処理中…",
        "p.mode": "モード: {mode}（グループ化 {group}）",
        "p.mode.video": "単一動画",
        "p.mode.playlist": "プレイリスト",
        "p.mode.on": "オン",
        "p.mode.off": "オフ",
        "p.transcoding": "再エンコード: {label}。",
        "p.done.playlist": "完了: {n} 動画 -> {dest}",
        "p.done.single": "完了: {title}",
        "p.cancelled": "ダウンロードはユーザーによってキャンセルされました。",
        "p.error": "エラー: {exc}",
        "p.ffmpeg_missing": "ffmpegが見つかりません: 結合・字幕・メタデータは利用できません。",
        "p.skip_not_mp4": "再エンコードをスキップ: ファイルがmp4ではありません。",
        "p.transcode_run": "再エンコード中（{vcodec}）...",
        "p.postprocess": "後処理（ffmpeg: 結合/HEVC/メタデータ/字幕/サムネイル）...",
    },
    "zh-CN": {
        "ui.sub": "下载 YouTube 视频和播放列表（yt-dlp）",
        "ui.settings": "设置",
        "ui.close": "关闭",
        "tab.video": "视频",
        "tab.playlist": "播放列表",
        "url.video.label": "视频链接：",
        "url.playlist.label": "播放列表链接：",
        "group.label": "分组：将播放列表保存到以其命名的子文件夹",
        "warn.ffmpeg": "未找到 ffmpeg — 合并、字幕、元数据和转码将不可用。",
        "ffmpeg.overlay_title": "安装 FFmpeg",
        "ffmpeg.overlay_hint": "合并视频和音频、字幕、元数据和转码需要 ffmpeg。",
        "ffmpeg.download": "下载 FFmpeg",
        "ffmpeg.downloading": "正在下载 ffmpeg… {pct}%",
        "ffmpeg.extracting": "正在解压 ffmpeg…",
        "ffmpeg.ready": "ffmpeg 已安装。",
        "ffmpeg.error": "下载 ffmpeg 失败：{exc}",
        "btn.download": "下载",
        "btn.stop": "取消",
        "status.ready": "就绪。",
        "status.enter.video": "请输入视频链接。",
        "status.enter.playlist": "请输入播放列表链接。",
        "status.playlist.warning": "这是播放列表链接：在“视频”标签页中只会下载单个视频。请打开“播放列表”标签页以下载全部内容。",
        "sheet.tab.ui": "界面",
        "sheet.tab.dl": "下载器",
        "sheet.dest.label": "下载文件夹：",
        "sheet.browse": "浏览…",
        "sheet.theme.label": "主题：",
        "sheet.subs.label": "字幕：",
        "sheet.qual.label": "画质限制：",
        "sheet.transcode.label": "转码：",
        "sheet.network.label": "网络",
        "sheet.retries.label": "重试次数：",
        "sheet.timeout.label": "超时（秒）：",
        "sheet.lang.label": "语言：",
        "subs.off": "关闭",
        "subs.ru": "俄语",
        "subs.en": "英语",
        "subs.all": "全部",
        "qual.lossless": "无损（最高）",
        "trans.none": "默认（无）",
        "trans.libx265": "HEVC（x265，软件）",
        "trans.nvenc": "NVIDIA NVENC（H.265）",
        "trans.amf": "AMD AMF（H.265）",
        "trans.qsv": "Intel Quick Sync (QSV)（H.265）",
        "trans.unavailable": "（不可用）",
        "trans.note.noffmpeg": "未找到 ffmpeg — 转码不可用。",
        "trans.note.missing": "您的 ffmpeg 版本中不可用：",
        "theme_scary_forest": "黑暗森林",
        "theme_technology_day": "科技之日",
        "theme_technology_pinks": "科技粉红",
        "theme_scarred_mind": "伤痕之心",
        "theme_audrey_main": "奥黛丽主色",
        "theme_night_sky": "夜空",
        "theme_vilmy": "Vilmy~",
        "clicker.title": "…",
        "clicker.hint": "点我呀~",
        "clicker.messages": [
            "把我点到死~~~",
            "再来，再来，别停下~",
            "快到了…就差一点~",
            "每点一下我就融化一点~",
            "你再点下去…我就要…你懂的~",
            "听到没有，我舒服得直响~",
        ],
        "p.retry_hls": "失败：尝试 HLS 流媒体 ({n})…",
        "p.done_errors": "已完成但有错误 — 部分文件未下载。",
        "p.ready": "就绪。",
        "p.start": "正在启动…",
        "p.enter_url": "请输入视频或播放列表链接。",
        "p.playlist_warn": "这是在“视频”标签页中打开的播放列表链接 — 只会下载单个视频。请使用“播放列表”标签页下载全部内容。",
        "p.stop_req": "正在停止…",
        "p.going": "正在下载…",
        "p.mbps": "MB/秒",
        "p.eta_prefix": "剩余",
        "p.eta_sec": "秒",
        "p.post": "后处理中…",
        "p.mode": "模式：{mode}（分组 {group}）",
        "p.mode.video": "单个视频",
        "p.mode.playlist": "播放列表",
        "p.mode.on": "开",
        "p.mode.off": "关",
        "p.transcoding": "转码：{label}。",
        "p.done.playlist": "完成：{n} 个视频 -> {dest}",
        "p.done.single": "完成：{title}",
        "p.cancelled": "下载已被用户取消。",
        "p.error": "错误：{exc}",
        "p.ffmpeg_missing": "未找到 ffmpeg：合并/字幕/元数据将不可用。",
        "p.skip_not_mp4": "跳过转码：文件不是 mp4。",
        "p.transcode_run": "正在转码（{vcodec}）...",
        "p.postprocess": "后处理（ffmpeg：合并/HEVC/元数据/字幕/缩略图）...",
    },
    "es": {
        "ui.sub": "Descarga vídeos y listas de reproducción de YouTube (yt-dlp)",
        "ui.settings": "Configuración",
        "ui.close": "Cerrar",
        "tab.video": "Vídeo",
        "tab.playlist": "Lista de reproducción",
        "url.video.label": "Enlace del vídeo:",
        "url.playlist.label": "Enlace de la lista:",
        "group.label": "Agrupar: guardar la lista en una subcarpeta con su nombre",
        "warn.ffmpeg": "No se encontró ffmpeg: la combinación, los subtítulos, los metadatos y la transcodificación no estarán disponibles.",
        "ffmpeg.overlay_title": "Instalar FFmpeg",
        "ffmpeg.overlay_hint": "ffmpeg es necesario para combinar vídeo y audio, subtítulos, metadatos y transcodificar.",
        "ffmpeg.download": "Descargar FFmpeg",
        "ffmpeg.downloading": "Descargando ffmpeg… {pct}%",
        "ffmpeg.extracting": "Extrayendo ffmpeg…",
        "ffmpeg.ready": "ffmpeg instalado.",
        "ffmpeg.error": "No se pudo descargar ffmpeg: {exc}",
        "btn.download": "Descargar",
        "btn.stop": "Cancelar",
        "status.ready": "Listo.",
        "status.enter.video": "Introduce un enlace de vídeo.",
        "status.enter.playlist": "Introduce un enlace de lista de reproducción.",
        "status.playlist.warning": "Es un enlace de lista: en la pestaña «Vídeo» solo se descargará el propio vídeo. Abre la pestaña «Lista de reproducción» para descargarlo todo.",
        "sheet.tab.ui": "Interfaz",
        "sheet.tab.dl": "Descargador",
        "sheet.dest.label": "Carpeta de descarga:",
        "sheet.browse": "Examinar…",
        "sheet.theme.label": "Tema:",
        "sheet.subs.label": "Subtítulos:",
        "sheet.qual.label": "Límite de calidad:",
        "sheet.transcode.label": "Transcodificación:",
        "sheet.network.label": "Red",
        "sheet.retries.label": "Reintentos:",
        "sheet.timeout.label": "Tiempo de espera (seg):",
        "sheet.lang.label": "Idioma:",
        "subs.off": "Apagado",
        "subs.ru": "Ruso",
        "subs.en": "Inglés",
        "subs.all": "Todos",
        "qual.lossless": "Lossless (máximo)",
        "trans.none": "Predeterminado (Ninguno)",
        "trans.libx265": "HEVC (x265, software)",
        "trans.nvenc": "NVIDIA NVENC (H.265)",
        "trans.amf": "AMD AMF (H.265)",
        "trans.qsv": "Intel Quick Sync (QSV) (H.265)",
        "trans.unavailable": "(no disponible)",
        "trans.note.noffmpeg": "No se encontró ffmpeg: la transcodificación no está disponible.",
        "trans.note.missing": "No disponibles en esta versión de ffmpeg: ",
        "theme_scary_forest": "Bosque Tenebroso",
        "theme_technology_day": "Día Tecnológico",
        "theme_technology_pinks": "Rosas Tecnológicos",
        "theme_scarred_mind": "Mente Marcada",
        "theme_audrey_main": "Colores de Audrey",
        "theme_night_sky": "Cielo Nocturno",
        "theme_vilmy": "Vilmy~",
        "clicker.title": "…",
        "clicker.hint": "¡Haz clic en mí~",
        "clicker.messages": [
            "¡Haz clic en mí hasta morir~~~",
            "Más, más, no te detengas~",
            "Estoy tan cerca… un poquito más~",
            "Cada clic me derrite~",
            "Me vas a clicar hasta… ya sabes~",
            "¿Oyes cómo chasqueo de placer~",
        ],
        "p.retry_hls": "Error: probando flujo HLS ({n})…",
        "p.done_errors": "Finalizado con errores: algunos archivos no se descargaron.",
        "p.ready": "Listo.",
        "p.start": "Iniciando…",
        "p.enter_url": "Introduce un enlace de vídeo o lista de reproducción.",
        "p.playlist_warn": "Es un enlace de lista abierto en la pestaña «Vídeo»: solo se descargará un vídeo. Utiliza la pestaña «Lista de reproducción» para descargarlo todo.",
        "p.stop_req": "Solicitud de detención…",
        "p.going": "descargando…",
        "p.mbps": "MB/s",
        "p.eta_prefix": "ETA",
        "p.eta_sec": "s",
        "p.post": "Postprocesado…",
        "p.mode": "Modo: {mode} (agrupación {group})",
        "p.mode.video": "vídeo único",
        "p.mode.playlist": "lista de reproducción",
        "p.mode.on": "sí",
        "p.mode.off": "no",
        "p.transcoding": "Transcodificación: {label}.",
        "p.done.playlist": "Listo: {n} vídeos -> {dest}",
        "p.done.single": "Listo: {title}",
        "p.cancelled": "Descarga cancelada por el usuario.",
        "p.error": "Error: {exc}",
        "p.ffmpeg_missing": "No se encontró ffmpeg: combinación/subtítulos/metadatos no estarán disponibles.",
        "p.skip_not_mp4": "Se omite la transcodificación: el archivo no es mp4.",
        "p.transcode_run": "Transcodificando ({vcodec})...",
        "p.postprocess": "Postprocesado (ffmpeg: combinación/HEVC/metadatos/subtítulos/miniatura)...",
    },
    "de": {
        "ui.sub": "YouTube-Videos und -Wiedergabelisten herunterladen (yt-dlp)",
        "ui.settings": "Einstellungen",
        "ui.close": "Schließen",
        "tab.video": "Video",
        "tab.playlist": "Wiedergabeliste",
        "url.video.label": "Video-Link:",
        "url.playlist.label": "Wiedergabelisten-Link:",
        "group.label": "Gruppieren: Wiedergabeliste in einen Unterordner mit ihrem Namen speichern",
        "warn.ffmpeg": "ffmpeg wurde nicht gefunden — Zusammenführen, Untertitel, Metadaten und Transkodierung sind nicht verfügbar.",
        "ffmpeg.overlay_title": "FFmpeg installieren",
        "ffmpeg.overlay_hint": "ffmpeg wird benötigt zum Zusammenführen von Video+Audio, Untertiteln, Metadaten und Transkodierung.",
        "ffmpeg.download": "FFmpeg herunterladen",
        "ffmpeg.downloading": "ffmpeg wird heruntergeladen… {pct}%",
        "ffmpeg.extracting": "ffmpeg wird entpackt…",
        "ffmpeg.ready": "ffmpeg installiert.",
        "ffmpeg.error": "ffmpeg-Download fehlgeschlagen: {exc}",
        "btn.download": "Herunterladen",
        "btn.stop": "Abbrechen",
        "status.ready": "Bereit.",
        "status.enter.video": "Bitte einen Video-Link eingeben.",
        "status.enter.playlist": "Bitte einen Wiedergabelisten-Link eingeben.",
        "status.playlist.warning": "Dies ist ein Listen-Link: Im Tab «Video» wird nur das einzelne Video heruntergeladen. Öffnen Sie den Tab «Wiedergabeliste», um alles zu laden.",
        "sheet.tab.ui": "Oberfläche",
        "sheet.tab.dl": "Downloader",
        "sheet.dest.label": "Download-Ordner:",
        "sheet.browse": "Durchsuchen…",
        "sheet.theme.label": "Design:",
        "sheet.subs.label": "Untertitel:",
        "sheet.qual.label": "Qualitätslimit:",
        "sheet.transcode.label": "Transkodierung:",
        "sheet.network.label": "Netzwerk",
        "sheet.retries.label": "Wiederholungen:",
        "sheet.timeout.label": "Zeitüberschreitung (Sek):",
        "sheet.lang.label": "Sprache:",
        "subs.off": "Aus",
        "subs.ru": "Russisch",
        "subs.en": "Englisch",
        "subs.all": "Alle",
        "qual.lossless": "Lossless (max)",
        "trans.none": "Standard (Keine)",
        "trans.libx265": "HEVC (x265, Software)",
        "trans.nvenc": "NVIDIA NVENC (H.265)",
        "trans.amf": "AMD AMF (H.265)",
        "trans.qsv": "Intel Quick Sync (QSV) (H.265)",
        "trans.unavailable": "(nicht verfügbar)",
        "trans.note.noffmpeg": "ffmpeg nicht gefunden — Transkodierung ist nicht verfügbar.",
        "trans.note.missing": "In dieser ffmpeg-Version nicht verfügbar: ",
        "theme_scary_forest": "Spukwald",
        "theme_technology_day": "Technik-Tag",
        "theme_technology_pinks": "Technik-Rosa",
        "theme_scarred_mind": "Narben-Geist",
        "theme_audrey_main": "Audrey-Farben",
        "theme_night_sky": "Nachthimmel",
        "theme_vilmy": "Vilmy~",
        "clicker.title": "…",
        "clicker.hint": "Klick mich~",
        "clicker.messages": [
            "Klick mich zu Tode~~~",
            "Mehr, mehr, hör nicht auf~",
            "Ich bin so nah… noch ein bisschen~",
            "Jeder Klick lässt mich schmelzen~",
            "Willst du mich klicken bis… du weißt schon~",
            "Hörst du, wie ich vor Vergnügen klicke~",
        ],
        "p.retry_hls": "Fehlgeschlagen: versuche HLS-Stream ({n})…",
        "p.done_errors": "Mit Fehlern fertig - einige Dateien wurden nicht heruntergeladen.",
        "p.ready": "Bereit.",
        "p.start": "Starte…",
        "p.enter_url": "Bitte einen Video- oder Listen-Link eingeben.",
        "p.playlist_warn": "Dies ist ein Listen-Link im Tab «Video» — nur das einzelne Video wird heruntergeladen. Verwenden Sie den Tab «Wiedergabeliste», um alles zu laden.",
        "p.stop_req": "Abbruch angefordert…",
        "p.going": "lädt herunter…",
        "p.mbps": "MB/s",
        "p.eta_prefix": "ETA",
        "p.eta_sec": "s",
        "p.post": "Nachbearbeitung…",
        "p.mode": "Modus: {mode} (Gruppierung {group})",
        "p.mode.video": "einzelnes Video",
        "p.mode.playlist": "Wiedergabeliste",
        "p.mode.on": "an",
        "p.mode.off": "aus",
        "p.transcoding": "Transkodierung: {label}.",
        "p.done.playlist": "Fertig: {n} Videos -> {dest}",
        "p.done.single": "Fertig: {title}",
        "p.cancelled": "Download vom Benutzer abgebrochen.",
        "p.error": "Fehler: {exc}",
        "p.ffmpeg_missing": "ffmpeg nicht gefunden: Zusammenführen/Untertitel/Metadaten sind nicht verfügbar.",
        "p.skip_not_mp4": "Transkodierung übersprungen: Datei ist kein mp4.",
        "p.transcode_run": "Transkodierung ({vcodec})...",
        "p.postprocess": "Nachbearbeitung (ffmpeg: Zusammenführen/HEVC/Metadaten/Untertitel/Thumbnail)...",
    },
}


def tr(lang: str, key: str, **kwargs) -> str:
    """Переводит строку по ключу, с подстановкой {…} при наличии аргументов."""
    d = I18N.get(lang) or I18N["ru"]
    text = d.get(key)
    if text is None:
        text = I18N["ru"].get(key) or key
    return text.format(**kwargs) if kwargs else text


# -- внешние переводы (JSON-файлы в %LOCALAPPDATA%\Synfronia\language) -------
_LANG_EXTS = {".json"}


def _lang_root() -> Path:
    r"""Папка переводов: %LOCALAPPDATA%\Synfronia\language."""
    base = os.environ.get("LOCALAPPDATA") or str(base_dir())
    return Path(base) / "Synfronia" / "language"


_LOADED_LANGS: tuple[str, ...] | None = None


def load_languages() -> tuple[str, ...]:
    """Сканирует папку переводов и подмешивает её файлы во встроенные переводы.

    • при первом запуске (папка пуста/нет файлов) записывает базовый
      «{lang}.json» для каждого встроенного языка — файлы можно править;
    • при каждом запуске читается каждый «*.json»: имя файла = код языка
      (например uk.json), содержимое = словарь ключей перевода, приоритет
      у файла. Новый язык автоматически попадает в список, возвращаемый
      этой функцией.
    """
    global _LOADED_LANGS
    root = _lang_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return LANGUAGES
    # 1) базовые файлы — создаём, только если их ещё нет
    for lang in LANGUAGES:
        payload = dict(I18N.get(lang, {}))
        payload.setdefault("thisLang", SELF_NAMES.get(lang) or lang)
        I18N[lang] = payload
        f = root / f"{lang}.json"
        if f.exists():
            continue
        try:
            f.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except OSError:
            pass
    # 2) сканируем папку: каждый «*.json» — язык (имя файла = код языка)
    found = []
    for f in sorted(root.glob("*.json")):
        lang = f.stem
        if not lang or not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z]{2,8})?", lang):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        merged = dict(I18N.get(lang, {}))
        merged.update(data)
        merged.setdefault("thisLang", SELF_NAMES.get(lang) or lang)
        I18N[lang] = merged
        found.append(lang)
    # базовые сначала (стабильный порядок), затем новые из папки
    order = list(LANGUAGES) + [l for l in found if l not in LANGUAGES]
    _LOADED_LANGS = tuple(dict.fromkeys(order))
    return _LOADED_LANGS


# -- внешние темы (папки в %LOCALAPPDATA%\Synfronia\themes) ------------------
# Каждая тема — отдельная подпапка {theme_id}/ с файлами:
#   theme.json   — палитра/прозрачность/скругление (поля см. THEMES выше);
#   custom.css   — дополнительный CSS темы (можно менять фон элементов,
#                  подставлять картинки: url("bg.png"), url("anim.gif") и т.д.);
#   любые файлы  — ресурсы темы, на них ссылаются относительными url(...).
# Имя файла CSS можно переопределить полем "css" в theme.json.
_THEME_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")

_THEME_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
}

_BASE_CSS = (
    "/* Дополнительный CSS темы. Ресурсы темы кладите рядом и подключайте "
    "относительно: url(\"bg.png\"), url(\"anim.gif\"). */\n"
)

_URLEX = re.compile(r"""url\(\s*(?:"([^"]*)"|'([^']*)'|([^)"'\s][^)"']*))\s*\)""")


def _themes_root() -> Path:
    r"""Папка тем: %LOCALAPPDATA%\Synfronia\themes."""
    base = os.environ.get("LOCALAPPDATA") or str(base_dir())
    return Path(base) / "Synfronia" / "themes"


_LOADED_THEMES: dict[str, dict] | None = None


def _asset_data_uri(path: Path) -> str | None:
    """Превращает локальный файл темы (png/gif/jpg/…) в data:URI."""
    mime = _THEME_MIME.get(path.suffix.lower())
    if mime is None:
        return None
    try:
        return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        return None


def _process_theme_css(css: str, folder: Path) -> str:
    """Подставляет локальные файлы темы в url(...) как data:URI.

    Относительные url(имя.расширение) резолвятся внутри папки темы и
    встраиваются в CSS; абсолютные (http/https/data://, пути с диском)
    остаются как есть.
    """
    folder = folder.resolve()

    def repl(m):
        rel = m.group(1) or m.group(2) or m.group(3)
        if not rel:
            return m.group(0)
        low = rel.lower()
        if (low.startswith("data:") or low.startswith("http://")
                or low.startswith("https://") or low.startswith("//")
                or low.startswith("file:") or low.startswith("/")
                or re.match(r"^[A-Za-z]:[\\/]", low) or low.startswith("\\\\")):
            return m.group(0)
        candidate = (folder / rel).resolve()
        if not candidate.is_relative_to(folder):
            return m.group(0)
        uri = _asset_data_uri(candidate)
        return f"url(\"{uri}\")" if uri else m.group(0)

    return _URLEX.sub(repl, css)


def _seed_theme(root: Path, key: str, payload: dict) -> None:
    """Раскладывает встроенную тему в папку (theme.json + custom.css),
    только если их ещё нет — правки пользователя сохраняются."""
    folder = root / key
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    meta = folder / "theme.json"
    if not meta.exists():
        try:
            meta.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8-sig",
            )
        except OSError:
            pass
    css = folder / "custom.css"
    if not css.exists():
        try:
            css.write_text(_BASE_CSS, encoding="utf-8-sig")
        except OSError:
            pass


def _migrate_flat(root: Path) -> None:
    """Переносит старые плоские «{theme}.json» (наследие предыдущей версии)
    в папку темы как theme.json; плоский файл после переноса удаляется."""
    for f in sorted(root.glob("*.json")):
        key = f.stem
        if not key or not _THEME_ID_RE.fullmatch(key):
            continue
        if (root / key / "theme.json").exists():
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        try:
            (root / key).mkdir(parents=True, exist_ok=True)
            (root / key / "theme.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8-sig",
            )
            f.unlink()
        except OSError:
            pass


def load_themes() -> dict[str, dict]:
    """Сканирует папку тем: каждая подпапка = тема (theme.json + custom.css).

    • при первом запуске (папка пуста/нет файлов) раскладывает базовые темы
      по папкам — файлы можно править, добавлять CSS и картинки;
    • при каждом запуске читается каждая «*/theme.json»: имя папки = id темы,
      содержимое = словарь полей палитры/прозрачности/скругления; рядом
      custom.css с ресурсами темы. Новая тема (новая подпапка) автоматически
      попадает в возвращаемый словарь (базовые идут первыми, затем новые).
    """
    global _LOADED_THEMES
    root = _themes_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return dict(THEMES)
    _migrate_flat(root)
    # 1) базовые темы — раскладываем по папкам, только если их ещё нет
    for key, payload in THEMES.items():
        _seed_theme(root, key, payload)
    # 2) сканируем папку: каждая подпапка с theme.json — тема
    merged = dict(THEMES)
    order = list(THEMES)
    for folder in sorted(root.iterdir()):
        if not folder.is_dir() or not _THEME_ID_RE.fullmatch(folder.name):
            continue
        key = folder.name
        meta = folder / "theme.json"
        if not meta.exists():
            continue
        try:
            data = json.loads(meta.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        css_name = str(data.get("css") or "custom.css")
        css = ""
        css_path = folder / css_name
        if css_path.exists():
            try:
                css = _process_theme_css(css_path.read_text(encoding="utf-8-sig"), folder)
            except (OSError, UnicodeDecodeError):
                css = ""
        base = dict(merged.get(key, {}))
        base.update(data)
        base.setdefault("label", key)
        base["css"] = css
        merged[key] = base
        if key not in order:
            order.append(key)
    _LOADED_THEMES = {k: merged[k] for k in order}
    return _LOADED_THEMES

SUBTITLE_OPTIONS = {
    "off": None,
    "ru": ["ru"],
    "en": ["en"],
    "all": ["all"],
}

QUALITY_FORMATS = {
    "lossless": "bv*+ba/b",
    "2k": "bv*[height<=1440]+ba/b[height<=1440]",
    "1080": "bv*[height<=1080]+ba/b[height<=1080]",
    "720": "bv*[height<=720]+ba/b[height<=720]",
    "480": "bv*[height<=480]+ba/b[height<=480]",
    "240": "bv*[height<=240]+ba/b[height<=240]",
}

QUALITY_LIMITS = {
    "2k": 1440,
    "1080": 1080,
    "720": 720,
    "480": 480,
    "240": 240,
}

TRANSCODERS = {
    "libx265": {
        "label": "HEVC (x265, программный)",
        "vcodec": "libx265",
        "tag": "hvc1",
        "args": ["-preset", "medium", "-crf", "23"],
    },
    "nvenc": {
        "label": "NVIDIA NVENC (H.265)",
        "vcodec": "hevc_nvenc",
        "tag": "hvc1",
        "args": ["-preset", "p5", "-cq", "23"],
    },
    "amf": {
        "label": "AMD AMF (H.265)",
        "vcodec": "hevc_amf",
        "tag": "hvc1",
        "args": ["-quality", "quality", "-rc", "cqp", "-qp_i", "23", "-qp_p", "23"],
    },
    "qsv": {
        "label": "Intel Quick Sync (QSV) (H.265)",
        "vcodec": "hevc_qsv",
        "tag": "hvc1",
        "args": ["-preset", "medium", "-global_quality", "23"],
    },
}

ENCODER_NAMES = {
    "libx265": "libx265",
    "nvenc": "hevc_nvenc",
    "amf": "hevc_amf",
    "qsv": "hevc_qsv",
}


# -- пути и настройки --------------------------------------------------------
def base_dir() -> Path:
    """Папка приложения: рядом с exe (frozen) или с исходниками."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def ffmpeg_local_dir() -> Path:
    r"""Каталог, куда приложение скачивает ffmpeg: %LOCALAPPDATA%\Synfronia\bin."""
    return Path(os.environ.get("LOCALAPPDATA", str(base_dir()))) / "Synfronia" / "bin"


def logs_dir() -> Path:
    r"""Каталог логов: %LOCALAPPDATA%\Synfronia\logs."""
    return Path(os.environ.get("LOCALAPPDATA", str(base_dir()))) / "Synfronia" / "logs"


_LOG_LOCK = threading.Lock()


def _file_log(level: str, msg: str) -> None:
    r"""Дописывает строку в дневной лог-файл: %LOCALAPPDATA%\Synfronia\logs\app_YYYY-MM-DD.log."""
    try:
        logs_dir().mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    day = time.strftime("%Y-%m-%d")
    path = logs_dir() / f"app_{day}.log"
    try:
        with _LOG_LOCK:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(f"[{stamp}] [{level}] {msg}\n")
    except OSError:
        pass


FFMPEG_DOWNLOAD_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"


def download_ffmpeg(on_progress=None, on_log=None) -> str | None:
    """Скачивает ffmpeg-release-essentials.zip и распаковывает ffmpeg.exe/ffprobe.exe
    в ffmpeg_local_dir(). Возвращает путь к ffmpeg.exe или None при ошибке.
    on_progress(percent: float) вызывается по мере скачивания (0..100)."""
    dest = ffmpeg_local_dir()
    exe_path = dest / "ffmpeg.exe"
    if exe_path.is_file():
        return str(exe_path)

    dest.mkdir(parents=True, exist_ok=True)
    zip_path = dest / "ffmpeg.zip"
    try:
        if on_log:
            on_log("info", "Скачиваю ffmpeg…")
        req = urllib.request.Request(
            FFMPEG_DOWNLOAD_URL,
            headers={"User-Agent": "Synfronia/1.3 (auto-installer)"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            received = 0
            with open(zip_path, "wb") as fh:
                while True:
                    chunk = resp.read(1 << 16)
                    if not chunk:
                        break
                    fh.write(chunk)
                    received += len(chunk)
                    if on_progress and total:
                        on_progress(received / total * 100.0)

        with zipfile.ZipFile(zip_path) as zf:
            for name in zf.namelist():
                base = Path(name).name
                if base in ("ffmpeg.exe", "ffprobe.exe"):
                    target = dest / base
                    with zf.open(name) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)

        zip_path.unlink(missing_ok=True)
        return str(exe_path) if exe_path.is_file() else None
    except Exception as exc:  # noqa: BLE001
        if on_log:
            on_log("error", f"ffmpeg download failed: {exc}")
        zip_path.unlink(missing_ok=True)
        return None


def default_download_dir() -> Path:
    """Базовая папка скачивания — downloads рядом с приложением."""
    return base_dir() / "downloads"


def settings_path() -> Path:
    r"""Путь к файлу настроек: %LOCALAPPDATA%\Synfronia\settings.json."""
    root = Path(os.environ.get("LOCALAPPDATA", str(base_dir()))) / "Synfronia"
    root.mkdir(parents=True, exist_ok=True)
    return root / "settings.json"


def load_settings() -> dict:
    settings = based_settings()
    path = settings_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            if "hevc" in data and "transcode" not in data:
                settings["transcode"] = "libx265" if data["hevc"] else "none"
            for key in DEFAULT_SETTINGS:
                if key in data:
                    settings[key] = data[key]
    except (OSError, json.JSONDecodeError):
        pass
    save_settings(settings)
    return settings


def save_settings(settings: dict) -> None:
    settings_path().write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def find_ffmpeg() -> str | None:
    """Ищет ffmpeg в локальной папке (LocaAppData), PATH и типовых местах (winget)."""
    local = ffmpeg_local_dir() / "ffmpeg.exe"
    if local.is_file():
        return str(local)
    found = shutil.which("ffmpeg")
    if found:
        return found
    candidates = (
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Links/ffmpeg.exe",
        Path(os.environ.get("ProgramFiles", "")) / "ffmpeg/bin/ffmpeg.exe",
    )
    for cand in candidates:
        if cand.is_file():
            return str(cand)
    return None


def available_transcoders(ffmpeg: str | None = None) -> list[str]:
    """Ключи перекодировщиков, доступных в текущей сборке ffmpeg."""
    ffmpeg = ffmpeg or find_ffmpeg()
    if not ffmpeg:
        return list(ENCODER_NAMES)
    try:
        proc = subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-encoders"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return list(ENCODER_NAMES)
    output = proc.stdout or ""
    return [name for name, enc in ENCODER_NAMES.items() if re.search(rf"\b{re.escape(enc)}\b", output)]


def is_playlist(url: str) -> bool:
    """Простая эвристика: признак ссылки на плейлист по ?list=."""
    return bool(_PLAYLIST_RE.search(url or ""))


class _StopDownload(Exception):
    pass


class TranscodePP(FFmpegPostProcessor):
    """Перекодирует видео выбранным кодировщиком (x265/NVENC/AMF/QSV)
    в отдельный файл с суффиксом «HEVC», удаляя оригинал — чтобы в папке
    оставался только перекодированный файл."""

    def __init__(self, downloader=None, encoder: str = "libx265", lang: str = "ru",
                 copy_subtitles: bool = False):
        super().__init__(downloader)
        self._config = TRANSCODERS.get(encoder) or TRANSCODERS["libx265"]
        self._lang = lang
        self._copy_subtitles = copy_subtitles

    def _output_name(self, filename: str) -> str:
        """Формирует имя выходного файла: base [HEVC].mp4"""
        stem = os.path.splitext(filename)[0]
        return f"{stem} [HEVC].mp4"

    @FFmpegPostProcessor._restrict_to(images=False)
    def run(self, info):
        filename = info.get("filepath")
        if not filename or info.get("ext", "").lower() != "mp4":
            self.to_screen(tr(self._lang, "p.skip_not_mp4"))
            return [], info
        cfg = self._config
        out_path = self._output_name(filename)
        if os.path.abspath(out_path) == os.path.abspath(filename):
            self.to_screen(tr(self._lang, "p.skip_not_mp4"))
            return [], info
        temp = f"{out_path}.tmp.mp4"

        # Список кодеров для попыток: сначала выбранный (NVENC/AMF/QSV),
        # при недоступном GPU-кодеке падаем на CPU libx265.
        candidates = [cfg["vcodec"].split("_")[0] if cfg["vcodec"] in ("hevc_nvenc", "hevc_amf", "hevc_qsv") else "libx265"]
        if cfg["vcodec"] != "libx265":
            candidates = ["nvenc" if cfg["vcodec"] == "hevc_nvenc" else ("amf" if cfg["vcodec"] == "hevc_amf" else ("qsv" if cfg["vcodec"] == "hevc_qsv" else "libx265"))]
            candidates.append("libx265")

        last_err = None
        for enc in candidates:
            enc_cfg = TRANSCODERS.get(enc) or TRANSCODERS["libx265"]
            if enc_cfg["vcodec"] == "libx265" and last_err is not None:
                self.to_screen(tr(self._lang, "p.transcode_fallback", vcodec="libx265"))
            self.to_screen(tr(self._lang, "p.transcode_run", vcodec=enc_cfg["vcodec"]))
            try:
                self.run_ffmpeg(
                    filename,
                    temp,
                    ["-map", "0:v:0", "-map", "0:a?"]
                    + ([ "-map", "0:s?", "-c:s", "copy" ] if self._copy_subtitles else [])
                    + ["-c:v", enc_cfg["vcodec"], "-tag:v", enc_cfg["tag"]]
                    + enc_cfg["args"]
                    + ["-c:a", "copy"],
                )
                if os.path.exists(temp):
                    os.replace(temp, out_path)
                    # Оригинал больше не нужен: в папке остаётся только
                    # перекодированный файл, иначе было бы два видео.
                    try:
                        os.remove(filename)
                    except OSError:
                        pass
                last_err = None
                break
            except FFmpegPostProcessorError as e:
                last_err = e
                self.to_screen(tr(self._lang, "p.transcode_failed", detail=str(e)[:120]))
                if os.path.exists(temp):
                    os.remove(temp)
                continue
            finally:
                if os.path.exists(temp):
                    os.remove(temp)
        if last_err is not None:
            self.to_screen(tr(self._lang, "p.transcode_all_failed"))
            return [], info
        info["filepath"] = out_path
        info["_filename"] = out_path
        return [], info


def _quality_suffix_name(filename: str, limit: int) -> str:
    """Добавляет к имени файла суффикс лимита качества ([<limit>p]),
    объединяя его с уже имеющимся суффиксом [HEVC], если такой есть."""
    stem, ext = os.path.splitext(filename)
    m = re.search(r" \[\d+(?:\.\d+)?p(?: HEVC)?\]$", stem)
    if m:
        tag = m.group(0)
        if " HEVC" in tag:
            stem = stem[: m.start()] + f" [{limit}p HEVC]"
        else:
            stem = stem[: m.start()] + f" [{limit}p]"
    elif stem.endswith(" [HEVC]"):
        stem = stem[: -len(" [HEVC]")] + f" [{limit}p HEVC]"
    else:
        stem = f"{stem} [{limit}p]"
    return stem + ext


class QualitySuffixPP(FFmpegPostProcessor):
    """Добавляет суффикс лимита качества (например [240p]) к готовому файлу,
    если исходное разрешение видео выше установленного ограничения."""

    def __init__(self, downloader=None, quality: str = "lossless", lang: str = "ru"):
        super().__init__(downloader)
        self._limit = QUALITY_LIMITS.get(quality)
        self._lang = lang

    def _source_height(self, info: dict) -> int | None:
        best = None
        for fmt in info.get("formats") or []:
            h = fmt.get("height")
            if h:
                best = max(best or 0, int(h))
        return best

    @FFmpegPostProcessor._restrict_to(images=False)
    def run(self, info):
        filename = info.get("filepath")
        if not filename or not self._limit:
            return [], info
        source = self._source_height(info)
        if not source or source <= self._limit:
            return [], info
        target = _quality_suffix_name(filename, self._limit)
        if os.path.abspath(target) == os.path.abspath(filename):
            return [], info
        try:
            os.replace(filename, target)
        except OSError:
            return [], info
        info["filepath"] = target
        info["_filename"] = target
        return [], info


class Downloader:
    """Запускает yt-dlp в рабочем потоке и стучится в UI через колбэки."""

    def __init__(self, on_log=None, on_progress=None, lang: str = "ru"):
        self._on_log = on_log or (lambda *_: None)
        self._on_progress = on_progress or (lambda *_: None)
        self._lang = lang if lang in LANGUAGES else "ru"
        self._stop = threading.Event()
        self._wd_done = threading.Event()
        self._errors = False
        self._finished = []

    def _t(self, key: str, **kwargs) -> str:
        return tr(self._lang, key, **kwargs)

    def stop(self) -> None:
        self._stop.set()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    @property
    def failed(self) -> bool:
        return self._errors

    # -- колбэки в yt-dlp -----------------------------------------------------
    def _log(self, level: str, msg: str) -> None:
        self._on_log(level, msg)

    def _retry_hook(self, n: int = 0) -> float:
        """Вызывается yt-dlp перед каждой ретраей (http/fragment).
        Если запрошена остановка — бросает _StopDownload, мгновенно обрывая цикл."""
        if self._stop.is_set():
            raise _StopDownload()
        return 0.0

    def _watchdog(self, ydl) -> None:
        """Фоновый сторож: при запросе остановки закрывает все активные
        HTTP-соединения yt-dlp, чтобы прервать блокирующий read и retry-цикл."""
        while not self._stop.wait(0.05):
            if self._wd_done.is_set():
                return
        try:
            director = ydl._request_director
            director.close()
        except Exception:  # noqa: BLE001
            pass

    class _Logger:
        def __init__(self, owner: "Downloader"):
            self._owner = owner

        def debug(self, msg): self._owner._log("debug", msg)
        def info(self, msg): self._owner._log("info", msg)
        def warning(self, msg): self._owner._log("warning", msg)
        def error(self, msg):
            self._owner._errors = True
            self._owner._log("error", msg)

    def _hook(self, d: dict) -> None:
        if self._stop.is_set():
            raise _StopDownload()
        status = d.get("status")
        if status == "finished" and d.get("filename"):
            self._finished.append(os.path.abspath(d["filename"]))
        if status in ("downloading", "finished"):
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            recvd = d.get("downloaded_bytes") or 0
            percent = (recvd / total * 100) if total else None
            self._on_progress(
                {
                    "status": status,
                    "filename": os.path.basename(d.get("filename") or ""),
                    "downloaded": recvd,
                    "total": total,
                    "percent": percent,
                    "speed": d.get("speed"),
                    "eta": d.get("eta"),
                }
            )
        elif status == "postprocessing":
            self._on_progress(
                {
                    "status": "postprocessing",
                    "filename": "",
                    "percent": None,
                    "msg": self._t("p.postprocess"),
                }
            )

    def _cleanup_orphans(self) -> None:
        bases = set()
        for path in map(os.path.abspath, self._finished):
            parent, name = os.path.split(path)
            m = re.search(r"(?i)\.f\d+\.", name)
            bases.add(os.path.join(parent, name[: m.start()]) if m else path)
        for base in bases:
            parent, name = os.path.split(base)
            if not os.path.isdir(parent):
                continue
            try:
                entries = os.listdir(parent)
            except OSError:
                continue
            for entry in entries:
                if not entry.startswith(name + "."):
                    continue
                rest = entry[len(name):]
                if rest.startswith(".f") or rest in (".part", ".webp", ".jpg", ".jpeg", ".png"):
                    try:
                        os.remove(os.path.join(parent, entry))
                    except OSError:
                        pass

    # -- опции yt-dlp ---------------------------------------------------------
    def _build_opts(
        self,
        dest: str,
        playlist: bool,
        group: bool,
        subtitles: str,
        quality: str,
    ) -> dict:
        if playlist and group:
            outtmpl = os.path.join(dest, "%(playlist_title)s", "%(title)s.%(ext)s")
        else:
            outtmpl = os.path.join(dest, "%(title)s.%(ext)s")

        subs_langs = SUBTITLE_OPTIONS.get(subtitles)
        _retries = int(load_settings().get("retries", 10))
        _timeout = int(load_settings().get("socket_timeout", 20))
        opts = {
            "outtmpl": outtmpl,
            "format": QUALITY_FORMATS.get(quality, QUALITY_FORMATS["lossless"]),
            "merge_output_format": "mp4",
            "restrictfilenames": True,
            "noplaylist": not playlist,
            "overwrites": True,
            "noprogress": True,
            "writethumbnail": True,
            "logger": self._Logger(self),
            "progress_hooks": [self._hook],
            "ignoreerrors": True,
            "retries": _retries,
            "fragment_retries": _retries,
            "socket_timeout": _timeout,
            "js_runtimes": {"node": {}},
            "retry_sleep_functions": {"http": self._retry_hook, "fragment": self._retry_hook},
        }
        if subs_langs:
            opts["writesubtitles"] = True
            opts["writeautomaticsub"] = True
            opts["subtitleslangs"] = subs_langs
        return opts

    def _add_ffmpeg(self, opts: dict) -> dict:
        ffmpeg = find_ffmpeg()
        if ffmpeg:
            opts["ffmpeg_location"] = ffmpeg
            opts["hls_prefer_native"] = False
        else:
            opts["hls_prefer_native"] = True
            self._log("warning", self._t("p.ffmpeg_missing"))
        return opts

    def _register_pps(self, ydl: YoutubeDL, subs_on: bool, transcode: str, quality: str) -> None:
        if transcode and transcode != "none":
            ydl.add_post_processor(TranscodePP(ydl, transcode, self._lang, subs_on))
        if subs_on:
            ydl.add_post_processor(FFmpegEmbedSubtitlePP(ydl))
        ydl.add_post_processor(FFmpegMetadataPP(ydl))
        ydl.add_post_processor(EmbedThumbnailPP(ydl))
        ydl.add_post_processor(QualitySuffixPP(ydl, quality, self._lang))

    def _format_candidates(self, quality: str) -> list:
        base = QUALITY_FORMATS.get(quality, QUALITY_FORMATS["lossless"])
        limit = QUALITY_LIMITS.get(quality)
        if limit:
            hls = (
                f"bv*[height<={limit}][protocol^=m3u8]+ba/"
                f"bv*[height<={limit}]+ba/b[height<={limit}]"
            )
        else:
            hls = "bv*[protocol^=m3u8]+ba/bv*+ba/b"
        return [base, hls] if hls != base else [base]

    # -- запуск ---------------------------------------------------------------
    def download(
        self,
        url: str,
        dest: str,
        playlist: bool = False,
        group: bool = True,
        subtitles: str = "en",
        quality: str = "lossless",
        transcode: str = "none",
    ) -> None:
        os.makedirs(dest, exist_ok=True)
        self._errors = False
        self._finished = []
        opts = self._build_opts(dest, playlist, group, subtitles, quality)
        subs_on = bool(SUBTITLE_OPTIONS.get(subtitles))
        mode = self._t("p.mode.playlist" if playlist else "p.mode.video")
        grouping = self._t("p.mode.on") if playlist and group else self._t("p.mode.off")
        self._log("info", self._t("p.mode", mode=mode, group=grouping))
        if transcode and transcode != "none":
            encoder = TRANSCODERS.get(transcode)
            label = self._t("trans." + transcode) if "trans." + transcode in I18N["ru"] else (encoder["label"] if encoder else transcode)
            self._log("info", self._t("p.transcoding", label=label))
        candidates = self._format_candidates(quality)
        for i, fmt in enumerate(candidates):
            self._errors = False
            self._finished = []
            if i:
                self._log("warning", self._t("p.retry_hls", n=i + 1))
            opts = self._build_opts(dest, playlist, group, subtitles, quality)
            opts["format"] = fmt
            info = None
            short = None
            try:
                self._wd_done.clear()
                with YoutubeDL(self._add_ffmpeg(opts)) as ydl:
                    threading.Thread(
                        target=self._watchdog, args=(ydl,), daemon=True, name="synfronia-watchdog"
                    ).start()
                    self._register_pps(ydl, subs_on, transcode, quality)
                    info = ydl.extract_info(url, download=True)
                    if info and info.get("_type") == "playlist":
                        done = [e for e in info.get("entries", []) if e]
                        short = self._t("p.done.playlist", n=len(done), dest=os.path.basename(dest))
                    elif info:
                        short = self._t("p.done.single", title=info.get("title", "?"))
            except _StopDownload:
                self._log("warning", self._t("p.cancelled"))
                return
            except Exception as exc:  # noqa: BLE001
                self._log("error", self._t("p.error", exc=exc))
                break
            finally:
                self._wd_done.set()
                self._stop.clear()
                self._on_progress({"status": "done"})
            if not self._errors:
                if short:
                    self._log("info", short)
                return
            self._cleanup_orphans()
            if info and info.get("_type") == "playlist":
                break
        if not self._errors:
            return
        self._log("warning", self._t("p.done_errors"))
        if short and info and info.get("_type") == "playlist":
            self._log("info", short)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Загрузка через core.py")
    parser.add_argument("url")
    parser.add_argument("--dest", default=str(default_download_dir()))
    parser.add_argument("--playlist", action="store_true")
    parser.add_argument("--no-group", action="store_true")
    parser.add_argument("--subtitles", choices=list(SUBTITLE_OPTIONS), default="en")
    parser.add_argument("--quality", choices=list(QUALITY_FORMATS), default="lossless")
    parser.add_argument("--transcode", choices=list(TRANSCODERS), default="none")
    parser.add_argument("--lang", choices=list(LANGUAGES), default="ru")
    args = parser.parse_args()

    def _log(level, msg):
        print(f"[{level}] {msg}")

    dl = Downloader(on_log=_log, lang=args.lang)
    dl.download(
        args.url, args.dest,
        playlist=args.playlist,
        group=not args.no_group,
        subtitles=args.subtitles,
        quality=args.quality,
        transcode=args.transcode,
    )