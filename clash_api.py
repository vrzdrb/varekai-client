"""
Минимальный async-клиент для REST API ядра (clash/mihomo compatible).
Порт/secret приложение берёт только из config.yaml / smart-config.yaml.
"""

from urllib.parse import quote

import httpx

# Запасной URL проверки задержки. Основной берётся из живого testUrl
# группы (/proxies) или из профиля — см. config.get_delay_test_url().
DEFAULT_DELAY_URL = "http://cp.cloudflare.com/generate_204"


class ClashAPI:
    def __init__(self, secret=""):
        self.base_url = "http://127.0.0.1:9090"
        headers = {"Authorization": f"Bearer {secret}"} if secret else {}
        # Параллельный тест задержек держит два десятка запросов сразу:
        # дефолтного пула httpx (20 keepalive) на это не хватало.
        self._client = httpx.AsyncClient(
            timeout=2.0,
            headers=headers,
            limits=httpx.Limits(max_connections=64, max_keepalive_connections=32),
        )

    async def aclose(self) -> None:
        try:
            await self._client.aclose()
        except Exception:
            pass

    async def get_proxies(self):
        try:
            r = await self._client.get(f"{self.base_url}/proxies")
            if r.status_code == 200:
                return r.json().get("proxies") or {}
        except Exception:
            pass
        return {}

    async def switch_proxy(self, group_name, node_name):
        try:
            r = await self._client.put(
                f"{self.base_url}/proxies/{quote(group_name, safe='')}",
                json={"name": node_name},
            )
            return r.status_code in (200, 204)
        except Exception:
            return False

    async def unpin_proxy(self, group_name):
        try:
            r = await self._client.delete(
                f"{self.base_url}/proxies/{quote(group_name, safe='')}"
            )
            return r.status_code in (200, 204)
        except Exception:
            return False

    async def proxy_delay(self, node_name, timeout_ms=5000, url=DEFAULT_DELAY_URL):
        """Задержка ОДНОЙ ноды. Ядро пишет результат в её history —
        его видят все группы, где нода состоит (один тест на узел).

        Клиентский таймаут = серверный + запас на RTT до локального API:
        прежние 30 с позволяли одному зависшему запросу держать очередь.
        """
        try:
            r = await self._client.get(
                f"{self.base_url}/proxies/{quote(node_name, safe='')}/delay",
                params={"timeout": str(timeout_ms), "url": url},
                timeout=timeout_ms / 1000.0 + 3.0,
            )
            if r.status_code == 200:
                delay = (r.json() or {}).get("delay")
                if isinstance(delay, (int, float)) and delay > 0:
                    return int(delay)
        except Exception:
            pass
        return None

    async def group_delay(self, group_name, timeout_ms=5000, url=DEFAULT_DELAY_URL):
        """Тест всех узлов группы одним запросом. Возвращает {node: delay}.

        ВНИМАНИЕ: эндпоинт сбрасывает фиксацию выбора в авто-группах
        (url-test/fallback) — для фонового определения активной ноды
        непригоден. Кнопкой «Проверить пинг» не используется: там нужна
        дедупликация узлов между группами.

        Клиентский таймаут щедрый: ядро может гонять членов группы не
        вполне параллельно, а обрыв запроса теряет весь результат.
        """
        try:
            r = await self._client.get(
                f"{self.base_url}/group/{quote(group_name, safe='')}/delay",
                params={"timeout": str(timeout_ms), "url": url},
                timeout=max(30.0, timeout_ms / 1000.0 + 10.0),
            )
            if r.status_code == 200:
                return r.json() or {}
        except Exception:
            pass
        return {}

    async def reload_config(self, yaml_text: str) -> bool:
        """Перечитать конфиг на живом ядре: PUT /configs?force=true.
        Процесс ядра не перезапускается. Payload вместо path — чтобы не
        зависеть от SAFE_PATHS. Активные соединения рвутся."""
        try:
            r = await self._client.put(
                f"{self.base_url}/configs",
                params={"force": "true"},
                json={"path": "", "payload": yaml_text},
                timeout=20.0,
            )
            return r.status_code in (200, 204)
        except Exception:
            return False

    async def get_connections(self):
        try:
            r = await self._client.get(f"{self.base_url}/connections")
            if r.status_code == 200:
                return r.json().get("connections") or []
        except Exception:
            pass
        return []

    async def close_connection(self, conn_id):
        try:
            r = await self._client.delete(
                f"{self.base_url}/connections/{quote(conn_id, safe='')}"
            )
            return r.status_code in (200, 204)
        except Exception:
            return False

    async def close_all_connections(self):
        try:
            r = await self._client.delete(f"{self.base_url}/connections")
            return r.status_code in (200, 204)
        except Exception:
            return False
