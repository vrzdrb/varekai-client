# varekai-client

<img width="646" height="552" alt="preview" src="https://github.com/user-attachments/assets/a46a8ddf-688d-476c-a5c8-3638834739f4" />


Кроссплатформенный лаунчер ядра mihomo с графической панелью управления
zashboard. Cам скачивает / обновляет ядро, ваш конфигурационный файл и панель,
запускает VPN и открывает панель управления

## Возможности

- При каждом запуске самостоятельно обновляет mihomo, zashboard и ваш конфиг
- Запускает VPN в TUN-режиме (с правами администратора)
- Открывает панель управления в отдельном окне
- Хранит три последние версии ядра и умеет откатываться назад
- Ядро работает независимо от программы: закрыли меню или терминал — VPN не упал
- Панель работает на встроенном Chromium (QtWebEngine) и сохраняет настройки пользователя

## Поддерживаемые платформы

| Платформа | Архитектуры |
|---|---|
| Windows 10/11 | x86_64 |
| MacOS 11+ | Apple Silicon, Intel |
| Linux (любой дистрибутив с GUI) | x86_64, arm64 |

## Требования

### Windows
- Windows 10/11, запуск от администратора
- WebView2 Runtime — входит в Edge; если панель не
  открылась, установите Evergreen-runtime с сайта Microsoft

### MacOS
- MacOS 11+
- Запуск из Terminal:
```bash
./varekai
```
- Если система блокирует приложение: ПКМ → «Открыть», либо в терминале:
```bash
xattr -d com.apple.quarantine varekai
```
- Пароль администратора при запуске

### Linux
- Любой дистрибутив с Wayland или X11
- polkit (`pkexec`)
- Стандартные системные библиотеки DE (OpenGL, fontconfig, D-Bus, NSS)

## Установка

1. Скачайте архив под вашу ОС из Releases и распакуйте в любую папку
   (на Windows — не в Program Files)
2. Запустите:
   - Windows: `varekai.exe` от администратора
   - Linux: `./varekai` в терминале из папки программы
   - macOS: `./varekai` в Terminal
3. Выберите пункт **1** — ядро, конфиг и панель скачаются / обновятся, VPN запустится,
   откроется панель управления

**Важно:** закрытие окна программы или терминала НЕ останавливает VPN — ядро
продолжает работать в фоне. **Остановка — только пункт 9.**

## Структура:

- `config.yaml` — ваш конфиг в формате .yaml (скачивается по ссылке из URL.txt)
- `mihomo-core` / `mihomo-core.exe` — ядро
- `archives/` — архивы ядра для отката
- `zashboard/` — панель управления
- `zashboard-profile/` — настройки панели (язык, тема, заставка и т.д.)
- `mihomo-core.log`, `zashboard.log` — логи для диагностики

## Сборка из исходников (для разработчиков)

- Python 3.10+
```bash
pip install requests pyyaml pywebview
```
- Linux дополнительно: `pyside6`, `qtpy`, `qt6-webengine`, `qt6-webchannel`
- Arch:
```bash
pacman -S pyside6 python-qtpy qt6-webengine qt6-webchannel
```
- Сборка:
```bash
pyinstaller --onedir --console --name varekai main.py
```
  на Windows:
```bash
pyinstaller --onedir --uac-admin --console --name varekai main.py`
```
