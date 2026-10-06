"""Allegro buyer API client.

Allegro has no public API for buyers, so this uses the same session cookie
(QXLSESSID) as the website. Request shapes follow
https://github.com/Przemko92/home-assistant-allegro (MIT).
"""
import aiohttp

from .api_helpers import request_json


class AllegroApi:
    # edge.allegro.pl sits behind a captcha for non-browser clients; the api
    # host answers the same endpoints with just the session cookie.
    BASE_URL = "https://api.allegro.pl"
    ORDERS_LIMIT = 25

    def __init__(self, session: aiohttp.ClientSession, cookie: str):
        self._session = session
        self._cookie = cookie

    async def request(self, path: str, api_ver: int, params: dict | None = None):
        headers = {
            "Cookie": f"QXLSESSID={self._cookie}",
            "Accept": f"application/vnd.allegro.public.v{api_ver}+json",
            "Accept-Language": "pl-PL",
            "Referer": "https://allegro.pl/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        return await request_json(
            self._session,
            "GET",
            f"{self.BASE_URL}{path}",
            headers=headers,
            params=params,
            label="Allegro",
            log_401_as_info=True,
        )

    async def get_login(self) -> str:
        data = await self.request("/users", 2)
        try:
            return data["accounts"]["allegro"]["login"]
        except (KeyError, TypeError) as err:
            raise Exception("Allegro API Error: unexpected user info response") from err

    async def get_order(self, order_id: str):
        """Order details: recipient address, timeline and pickup point."""
        return await self.request(f"/myorder-api/myorders/{order_id}", 3)

    async def get_orders(self):
        return await self.request(
            "/myorder-api/myorders",
            3,
            params={
                "filter": "all",
                "limit": str(self.ORDERS_LIMIT),
                "offset": "0",
                "sort": "orderdate",
                "order": "DESC",
            },
        )
