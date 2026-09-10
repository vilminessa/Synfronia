<div align="center">

# YTdownloader

Скачивание видео и целых плейлистов YouTube с **вшиванием метаданных,
субтитров и обложки**, конвертацией в **HEVC** — в простом
десктопном приложении Windows на основе [yt-dlp](https://github.com/yt-dlp/yt-dlp).

![Python](https://img.shields.io/badge/Python-3.14-blue?logo=python&logoColor=white)
![GUI](https://img.shields.io/badge/GUI-Tkinter-8A2BE2)
![License](https://img.shields.io/badge/license-PolyForm%20Noncommercial-important)
![Build](https://img.shields.io/badge/build-PyInstaller-orange)

</div>

---

## Возможности

- **Видео и плейлисты** — вставьте ссылку, нажмите «Скачать»; плейлист можно
  скачать целиком или одним файлом (склейка частей).
- **Качество** — `lossless` (исходное), `1080`, `720`, `240`.
- **Субтитры** — вшиваются в файл: `нет / русские / английские / все`.
- **HEVC (H.265)** — опциональная конвертация в `libx265` со звуком без
  перекодирования, тегом `hvc1`, ~вдвое меньший размер при том же качестве.
- **Метаданные и обложка** — теги (название, автор, дата), превью вшивается
  как вложение (attached picture).
- **Три темы оформления**: Scary Forest, Technology day, Technology Pinks.
- **Ход загрузки и отмена** — прогресс-бар из логов yt-dlp, кнопка «Стоп».
- **Настройки сохраняются** в `settings.json` рядом с приложением.

## Требования

- Windows (для exe-версии больше ничего не нужно).
- Из исходников: Python 3.12+ и внешний **ffmpeg** в `PATH`
  (приложение найдёт его автоматически) — требуется для склейки,
  метаданных и конвертации.

## Установка

### Готовый exe

Скачайте `YTdownloader.exe` из [релизов](../../releases), запустите —
приложение готово к работе. Рядом с ним положите
`THIRD_PARTY_NOTICES.md` (лицензии компонентов).

### Из исходников

```bat
git clone https://github.com/vilminessa/YTdownloader.git
cd YTdownloader
pip install -r requirements.txt
python gui.py
```

## Использование

| Поле / настройка | Описание |
|---|---|
| Ссылка | URL видео или плейлиста YouTube |
| Каталог | куда сохранять (по умолчанию `downloads\` рядом с приложением) |
| Качество | `lossless` / 1080 / 720 / 240 |
| Субтитры | off / ru / en / all (вшиваются в контейнер) |
| HEVC | конвертировать в H.265 (`hvc1`, crf 23, preset medium) |
| Сгруппировать плейлист | скачать плейлист одним архивом |

### CLI

```bat
python download.py <URL> [--subtitles ru] [--quality 720] [--hevc] [--dir C:\videos]
```

### Самопроверка (для отладки сборки)

```bat
YTdownloader.exe --selftest C:\videos https://youtu.be/GUS0q7gZdNE --subtitles ru --quality 720 --hevc
```

Результаты пишутся в `selftest.log`, файлы — в указанный каталог.

## Сборка exe

```bat
python -m PyInstaller --onefile --windowed --name YTdownloader `
  --distpath . --workpath build --specpath . --collect-all yt_dlp gui.py
```

## Состав

```
core.py          — движок загрузки (обвязка над yt-dlp)
gui.py           — интерфейс Tkinter + скрытый режим --selftest
download.py      — CLI-обёртка
requirements.txt — yt-dlp, pyinstaller
LICENSE          — лицензия проекта (PolyForm Noncommercial 1.0.0)
THIRD_PARTY_NOTICES.md — источники и лицензии всех компонентов
```

## Источники компонентов

Проект построен на следующих сторонних компонентах
(полные тексты лицензий — в [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)):

| Компонент | Лицензия | Источник |
|---|---|---|
| yt-dlp | Unlicense (public domain) | https://github.com/yt-dlp/yt-dlp |
| PyInstaller (только сборка) | GPL-2.0+ с исключением | https://github.com/pyinstaller/pyinstaller |
| ffmpeg (внешний, не входит в exe) | GPL | https://ffmpeg.org/ |
| Python / tkinter | PSF | https://www.python.org/ |
| certifi, urllib3, idna, cffi, cryptography | MPL-2.0 / MIT / BSD-3 / MIT-0 / Apache-2.0 | см. notices |

Цвета интерфейса взяты из палитр [color-hex.com](https://color-hex.com/).

## Лицензия

Проект распространяется по **PolyForm Noncommercial License 1.0.0** —
разрешено использование, изучение, изменение и распространение в
**некоммерческих целях** (личные проекты, обучение, научные и
благотворительные организации и т.д.). **Продажа** этого продукта или
продуктов на его основе запрещена. Полный текст — в [`LICENSE`](LICENSE).

Примечание: эта лицензия не соответствует определению «Open Source»
по стандарту OSI и является **source-available** (открытые исходники с
ограничением на коммерцию).

## Disclaimer

Этот проект предназначен для личного некоммерческого использования —
например, для сохранения доступа к контенту. Пожалуйста, соблюдайте
[Правила сообщества YouTube](https://www.youtube.com/static?template=terms)
и авторские права: скачивайте только тот контент, который у вас есть
право сохранять, и не распространяйте полученные файлы без разрешения
правообладателя. Автор проекта не несёт ответственности за неправомерное
использование.

---

© 2026 [vilminessa](https://github.com/vilminessa) · PolyForm Noncommercial 1.0.0