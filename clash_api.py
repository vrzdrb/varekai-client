"""
Минимальный async-клиент для REST API ядра (clash/mihomo compatible).
Порт/secret приложение берёт только из config.yaml / smart-config.yaml.
"""
from urllib.parse import quote

import httpx


class ClashAPI:
    def __init__(self, secret=""):
        self.base_url = "http://127.0.0.1:9090"
        headers = {"Authorization": f"Bearer {secret}"} if secret else {}
        self._client = httpx.AsyncClient(timeout=2.0, headers=headers)

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
                f"{self.base_url}/proxies/{group_name}",
                json={"name": node_name},
            )
            return r.status_code in (200, 204)
        except Exception:
            return False

    async def unpin_proxy(self, group_name):
        try:
            r = await self._client.delete(f"{self.base_url}/proxies/{group_name}")
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
