import requests
from pathlib import Path
from utils import print_info, print_error, get_os, get_arch, check_avx2_support
from constants import MIRRORS_FILE, DEFAULT_MIRRORS
from i18n import t


def ensure_mirrors_file():
    """Создаёт mirrors.txt с дефолтами, если файла нет"""
    if not MIRRORS_FILE.exists():
        MIRRORS_FILE.write_text("\n".join(DEFAULT_MIRRORS) + "\n", encoding="utf-8")

def load_mirrors():
    """Читает список зеркал: по префиксу на строку, # и пустые строки игнорируются"""
    ensure_mirrors_file()
    mirrors = []
    for line in MIRRORS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            if not line.endswith("/"):
                line += "/"
            mirrors.append(line)
    return mirrors

def download_with_fallback(url, dest_path):
    """Скачивает файл: сначала напрямую, затем через зеркала из mirrors.txt.
    Возвращает (успех, ошибка)."""
    candidates = [""] + load_mirrors()
    for prefix in candidates:
        if prefix:
            print_info(t("gh_mirror", prefix=prefix))
        try:
            response = requests.get(
                prefix + url,
                stream=True,
                timeout=5 if prefix == "" else 30
            )
            if response.status_code != 200:
                continue
            with open(dest_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True, None
        except requests.exceptions.RequestException:
            continue
    return False, t("gh_all_fail")

def get_latest_tag_via_redirect(repo):
    """Получает тег последнего релиза через редирект releases/latest
    (работает через зеркала, не требует API)"""
    url = f"https://github.com/{repo}/releases/latest"
    for prefix in [""] + load_mirrors():
        try:
            r = requests.head(
                prefix + url,
                allow_redirects=True,
                timeout=5 if prefix == "" else 10
            )
            if r.status_code == 200 and "/tag/" in r.url:
                return r.url.rstrip("/").split("/tag/")[-1], None
        except requests.exceptions.RequestException:
            continue
    return None, t("gh_tag_fail")

def get_latest_release_info(repo):
    """Возвращает (tag, assets, error). assets пуст, если API недоступен —
    тогда имя ассета собирается детерминированно по схеме имён."""
    try:
        r = requests.get(
            f"https://api.github.com/repos/{repo}/releases/latest",
            timeout=5,
            headers={"User-Agent": "Varekai-Client"}
        )
        if r.status_code == 200:
            data = r.json()
            return data.get("tag_name"), data.get("assets", []), None
    except requests.exceptions.RequestException:
        pass
    print_info(t("gh_api_fail"))
    tag, err = get_latest_tag_via_redirect(repo)
    return tag, [], err

def github_download_url(repo, tag, asset_name):
    """Прямая ссылка на ассет релиза (проксируется зеркалами как есть)"""
    return f"https://github.com/{repo}/releases/download/{tag}/{asset_name}"

def build_core_asset_name(tag):
    """Детерминированно собирает имя ассета prizrak-core по схеме имён,
    когда список ассетов через API получить не удалось"""
    os_name = get_os()
    arch = get_arch()
    micro = ""
    if arch == "amd64":
        micro = "-v3" if check_avx2_support() else "-v1"
    ext = ".zip" if os_name == "windows" else ".gz"
    return f"prizrak-core-{os_name}-{arch}{micro}-{tag}{ext}"

def find_asset_for_platform(assets):
    """Ищет подходящий бинарник для текущей платформы"""
    os_name = get_os()
    arch = get_arch()
    avx2_supported = check_avx2_support()
    if arch == "amd64":
        target_microarch = "v3" if avx2_supported else "v1"
    else:
        target_microarch = None
    package_extensions = ('.deb', '.rpm', '.pkg.tar.zst')
    candidates = []
    for asset in assets:
        name = asset["name"].lower()
        if os_name not in name:
            continue
        if arch not in name:
            continue
        if any(name.endswith(ext) for ext in package_extensions):
            continue
        if os_name == "windows" and not name.endswith(".zip"):
            continue
        if os_name != "windows" and not name.endswith(".gz"):
            continue
        if "compatible" in name:
            continue
        if arch == "amd64" and target_microarch:
            if target_microarch == "v3":
                if "-v3-" not in name:
                    continue
            elif target_microarch == "v1":
                if "-v2-" in name or "-v3-" in name:
                    continue
        # Приоритет: 3 = без суффикса версии Go, 2 = с суффиксом версии Go
        has_go_suffix = any(f"-go{ver}-" in name for ver in ["120", "121", "122", "123", "124"])
        priority = 2 if has_go_suffix else 3
        candidates.append((priority, asset))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]
