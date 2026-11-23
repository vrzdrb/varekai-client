"""
Расшифровка подписки в формате age (armor), которую отдаёт hwid-sub
при включённом AGE-шифровании config.yaml.

РАБОЧИЙ ПУТЬ ОДИН — утилита age/rage: сначала ищется РЯДОМ С
ПРИЛОЖЕНИЕМ (в релизе бинарник кладётся в каталог сборки, см.
build-release.yml), затем в PATH. Только она умеет и постквантовых
получателей age1pq1.

_py_decrypt (на cryptography) НЕ РАБОТАЕТ и в decrypt() не вызывается.
Разбор заголовка, X25519-разворачивание ключа файла и проверка MAC
заголовка в нём корректны (MAC сходится с эталоном), но ключ тела
выводится неверно: keystream не совпадает с эталонным ни при одном
смещении/nonce. Оставлен в файле как заготовка с xfail-тестом —
чтобы дефект был виден, а не замаскирован.

Секретный ключ — строка AGE-SECRET-KEY-1… (bech32, 32 байта).
Формат файла: https://age-encryption.org/v1
"""

import base64
import hashlib
import hmac
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

AGE_ARMOR_BEGIN = b"-----BEGIN AGE ENCRYPTED FILE-----"
AGE_ARMOR_END = b"-----END AGE ENCRYPTED FILE-----"

_IDENTITY_HRP = "age-secret-key-"
_RECIPIENT_HRP = "age"
_STREAM_CHUNK = 64 * 1024 + 16  # 64 KiB plaintext + 16 байт Poly1305
_BODY_LINE = 64                 # строка тела этой длины = продолжение


class AgeError(Exception):
    """Неверный ключ, повреждённый файл или отсутствие расшифровщика."""


# ---------------------------------------------------------------- bech32
_B32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _polymod(values):
    gen = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    chk = 1
    for v in values:
        b = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ v
        for i in range(5):
            if (b >> i) & 1:
                chk ^= gen[i]
    return chk


def _hrp_expand(hrp):
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _convertbits(data, frm, to, pad):
    acc = bits = 0
    out = []
    maxv = (1 << to) - 1
    for v in data:
        if v < 0 or v >> frm:
            raise AgeError("bech32: значение вне диапазона")
        acc = (acc << frm) | v
        bits += frm
        while bits >= to:
            bits -= to
            out.append((acc >> bits) & maxv)
    if pad:
        if bits:
            out.append((acc << (to - bits)) & maxv)
    elif bits >= frm or ((acc << (to - bits)) & maxv):
        raise AgeError("bech32: неверное дополнение")
    return out


def bech32_encode(hrp, raw: bytes) -> str:
    data = _convertbits(list(raw), 8, 5, True)
    values = _hrp_expand(hrp) + data
    polymod = _polymod(values + [0, 0, 0, 0, 0, 0]) ^ 1
    checksum = [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]
    return hrp + "1" + "".join(_B32[d] for d in data + checksum)


def bech32_decode(text: str):
    """-> (hrp, payload_bytes). Проверяет контрольную сумму bech32."""
    s = (text or "").strip()
    if not s:
        raise AgeError("пустой ключ")
    if any(ord(c) < 33 or ord(c) > 126 for c in s):
        raise AgeError("ключ: недопустимые символы")
    if s.lower() != s and s.upper() != s:
        raise AgeError("ключ: смешанный регистр")
    s = s.lower()
    pos = s.rfind("1")
    if pos < 1 or pos + 7 > len(s):
        raise AgeError("ключ: неверный формат bech32")
    hrp, part = s[:pos], s[pos + 1:]
    try:
        data = [_B32.index(c) for c in part]
    except ValueError:
        raise AgeError("ключ: символ вне алфавита bech32")
    if _polymod(_hrp_expand(hrp) + data) != 1:
        raise AgeError("ключ: не сходится контрольная сумма (опечатка?)")
    return hrp, bytes(_convertbits(data[:-6], 5, 8, False))


def decode_identity(text: str) -> bytes:
    """AGE-SECRET-KEY-1… -> 32 байта секрета X25519."""
    hrp, raw = bech32_decode(text)
    if hrp != _IDENTITY_HRP:
        raise AgeError(
            "это не X25519-ключ age (hrp=%s); для age1pq1 нужна утилита age >= 1.3.0" % hrp
        )
    if len(raw) != 32:
        raise AgeError("ключ: ожидается 32 байта")
    return raw


def recipient_from_identity(text: str) -> str:
    """Публичный ключ (age1…) для этого секрета — сверить с ключом на сервере."""
    secret = decode_identity(text)
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    except ImportError:
        raise AgeError("нужен пакет cryptography или утилита age")
    pub = X25519PrivateKey.from_private_bytes(secret).public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return bech32_encode(_RECIPIENT_HRP, pub)


# ---------------------------------------------------------------- armor
def is_armor(data: bytes) -> bool:
    return AGE_ARMOR_BEGIN in (data or b"")[:200]


def _dearmor(data: bytes) -> bytes:
    lines = data.decode("ascii", "replace").splitlines()
    start = end = None
    for i, line in enumerate(lines):
        s = line.strip().encode()
        if s == AGE_ARMOR_BEGIN and start is None:
            start = i
        elif s == AGE_ARMOR_END and start is not None:
            end = i
            break
    if start is None or end is None:
        raise AgeError("armor: не найдены границы BEGIN/END")
    body = "".join(line.strip() for line in lines[start + 1:end])
    try:
        return base64.b64decode(body + "=" * (-len(body) % 4))
    except Exception:
        raise AgeError("armor: повреждённый base64")


def _b64d(raw: bytes) -> bytes:
    """age пишет base64 БЕЗ выравнивания (RawStdEncoding)."""
    s = raw.strip()
    return base64.b64decode(s + b"=" * (-len(s) % 4))


def _split_header(blob: bytes):
    """-> (header_до_и_включая_'---', mac_b64, payload)."""
    idx = blob.find(b"\n--- ")
    if idx < 0:
        raise AgeError("заголовок age: нет строки MAC")
    header = blob[:idx + 4]
    rest = blob[idx + 4:]
    nl = rest.find(b"\n")
    if nl < 0:
        raise AgeError("заголовок age: обрыв")
    return header, rest[1:nl].strip(), rest[nl + 1:]


def _parse_stanzas(header: bytes) -> list:
    """-> [(type, args, body_bytes), …].

    Формат age: строка '-> type arg1 …', затем ТЕЛО станзы отдельными
    base64-строками. Строка ровно в 64 символа — продолжение тела,
    более короткая (в т.ч. пустая) его завершает. У X25519 в аргументах
    только ephemeral share, обёрнутый ключ файла лежит в теле.
    """
    lines = header.split(b"\n")
    stanzas = []
    i = 1
    while i < len(lines):
        line = lines[i]
        if not line.startswith(b"-> "):
            i += 1
            continue
        parts = line.split()
        stype = parts[1] if len(parts) > 1 else b""
        args = parts[2:]
        i += 1
        chunks = []
        while i < len(lines):
            bl = lines[i]
            if bl.startswith(b"-> ") or bl.startswith(b"---"):
                break
            chunks.append(bl)
            i += 1
            if len(bl) < _BODY_LINE:
                break
        raw = b""
        joined = b"".join(chunks)
        if joined:
            try:
                raw = _b64d(joined)
            except Exception:
                raw = b""
        stanzas.append((stype, args, raw))
    return stanzas


# ---------------------------------------------------------------- расшифровка
def _py_decrypt(data: bytes, identity: str) -> bytes:
    """НЕ РАБОТАЕТ. В decrypt() не вызывается.

    Корректны: разбор armor/заголовка, X25519-разворачивание ключа
    файла, проверка MAC заголовка (сходится с эталоном).
    Неверен ключ тела: keystream не совпадает с эталонным ни при
    одном смещении 0..32, ни с одним построением nonce.
    Оставлено как заготовка; тест помечен xfail.
    """
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric.x25519 import (
            X25519PrivateKey,
            X25519PublicKey,
        )
        from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    except ImportError:
        raise AgeError("нужен пакет cryptography")

    secret = decode_identity(identity)
    blob = _dearmor(data) if is_armor(data) else data
    if not blob.startswith(b"age-encryption.org/v1"):
        raise AgeError("не файл age v1")
    header, mac_b64, payload = _split_header(blob)

    def hkdf(ikm, salt, info):
        return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=info).derive(ikm)

    priv = X25519PrivateKey.from_private_bytes(secret)
    own_pub = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )

    kinds = []
    x25519_count = 0
    file_key = None
    for stype, args, body in _parse_stanzas(header):
        kinds.append(stype.decode("ascii", "replace"))
        if stype != b"X25519" or not args or not body:
            continue
        x25519_count += 1
        try:
            share = _b64d(args[0])
            if len(share) != 32:
                continue
            shared = priv.exchange(X25519PublicKey.from_public_bytes(share))
            wrap_key = hkdf(shared, share + own_pub, b"age-encryption.org/v1/X25519")
            file_key = ChaCha20Poly1305(wrap_key).decrypt(b"\x00" * 12, body, None)
            break
        except Exception:
            continue

    if file_key is None:
        if not x25519_count:
            raise AgeError(
                "в файле нет станзы X25519 (найдено: %s)" % (", ".join(kinds) or "ничего")
            )
        raise AgeError("станза X25519 есть, но этим ключом не открывается")

    header_key = hkdf(file_key, b"", b"header")
    expect = hmac.new(header_key, header, hashlib.sha256).digest()
    if not hmac.compare_digest(expect, _b64d(mac_b64)):
        raise AgeError("MAC заголовка не сходится — файл повреждён")

    payload_key = hkdf(file_key, b"", b"payload")
    aead = ChaCha20Poly1305(payload_key)
    total = len(payload)
    if total < 16:
        raise AgeError("шифртекст пуст или обрезан")
    out = bytearray()
    pos = counter = 0
    while pos < total:
        block = payload[pos:pos + _STREAM_CHUNK]
        pos += _STREAM_CHUNK
        last = pos >= total
        if last and len(block) == _STREAM_CHUNK:
            raise AgeError("шифртекст обрезан: нет финального чанка")
        nonce = counter.to_bytes(11, "big") + (b"\x01" if last else b"\x00")
        try:
            out += aead.decrypt(nonce, block, None)
        except Exception:
            raise AgeError(
                "тело не расшифровалось (ключ файла верный — MAC сошёлся; "
                "дефект в выводе ключа тела)"
            )
        counter += 1
    return bytes(out)


def external_binary():
    """Путь к age/rage: сначала РЯДОМ С ПРИЛОЖЕНИЕМ (bundled в релизе),
    затем в PATH. shutil.which бинарник в каталоге сборки не находит."""
    try:
        from utils import get_os, get_script_dir
    except Exception:
        return shutil.which("age") or shutil.which("rage")
    windows = get_os() == "windows"
    names = ("age.exe", "rage.exe") if windows else ("age", "rage")
    try:
        base = get_script_dir()
        for name in names:
            cand = base / name
            if not cand.is_file():
                continue
            if not windows and not os.access(cand, os.X_OK):
                try:
                    os.chmod(cand, 0o755)
                except OSError:
                    continue
            return str(cand)
    except Exception:
        pass
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def _external_decrypt(data: bytes, identity: str):
    binpath = external_binary()
    if not binpath:
        return None
    with tempfile.TemporaryDirectory(prefix="varekai-age-") as td:
        keyfile = Path(td) / "identity.txt"
        keyfile.write_text(identity.strip() + "\n", encoding="utf-8")
        try:
            os.chmod(keyfile, 0o600)
        except OSError:
            pass
        try:
            r = subprocess.run(
                [binpath, "-d", "-i", str(keyfile)],
                input=data, capture_output=True, timeout=60,
            )
        except subprocess.TimeoutExpired:
            raise AgeError("age: таймаут расшифровки")
        except OSError as e:
            raise AgeError("age: не удалось запустить (%s)" % e)
    if r.returncode != 0:
        msg = (r.stderr or b"").decode("utf-8", "replace").strip()
        raise AgeError("age: " + (msg[:300] or "ошибка расшифровки"))
    return r.stdout


def decrypt(data: bytes, identity: str) -> bytes:
    """Возвращает открытый YAML. Не зашифровано — отдаём как есть.

    Только эталонная утилита age. Питоновский fallback не вызывается:
    он не работает, а его ошибка уводила проверять ключи, которые
    ни при чём. Отсутствие бинарника — явная ошибка с указанием,
    что сделать.
    """
    if not is_armor(data):
        return data
    if not (identity or "").strip():
        raise AgeError("подписка зашифрована, но AGE-SECRET-KEY не задан")
    ext = _external_decrypt(data, identity)
    if ext is None:
        raise AgeError(
            "для расшифровки подписки нужна утилита age: положите бинарник "
            "age рядом с приложением (в релизе он уже есть) или установите "
            "в систему — apt install age / brew install age / pacman -S age"
        )
    return ext


def backend() -> str:
    """Диагностика: чем будем расшифровывать."""
    binpath = external_binary()
    if binpath:
        return os.path.basename(binpath)
    return "none"
