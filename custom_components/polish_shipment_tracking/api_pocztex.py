import aiohttp
import html
import re
import secrets
import time
import urllib.parse

from .api_helpers import request_json

"""
Authorization is basically:
1. GET standard login page to get form and hidden fields
2. POST login form with email and password
3. Parse redirect URL to get authorization code
4. POST to token endpoint with authorization code to get access and refresh tokens
"""
class PocztexApi:
    API_BASE_URL = "https://aplikacja.pocztex.pl/api/customer"
    AUTH_BASE_URL = "https://idm.pocztex.pl"
    AUTH_REALM = "ppsa"
    CLIENT_ID = "mobile"
    REDIRECT_URI = "pocztex://auth/redirect"
    SCOPE = "offline_access"
    APP_VERSION = "1.0.12"
    LANGUAGE = "PL"
    LOGIN_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:147.0) "
        "Gecko/20100101 Firefox/147.0"
    )
    LOGIN_ACCEPT_LANGUAGE = "en-US,en;q=0.9"
    LOGIN_ORIGIN = "null"

    def __init__(self, session: aiohttp.ClientSession):
        self._session = session
        self._token = None
        self._refresh_token = None
        self._expires_at = 0
        self._refresh_expires_at = 0

    def _token_url(self):
        base = self.AUTH_BASE_URL.rstrip("/")
        realm = str(self.AUTH_REALM).strip("/")
        return f"{base}/realms/{realm}/protocol/openid-connect/token"

    def _authorize_url(self, state):
        base = self.AUTH_BASE_URL.rstrip("/")
        realm = str(self.AUTH_REALM).strip("/")
        auth_url = f"{base}/realms/{realm}/protocol/openid-connect/auth"
        params = {
            "client_id": self.CLIENT_ID,
            "response_type": "code",
            "redirect_uri": self.REDIRECT_URI,
        }
        if self.SCOPE:
            params["scope"] = self.SCOPE
        if state:
            params["state"] = state
        return f"{auth_url}?{urllib.parse.urlencode(params)}"

    async def _request_json(self, method, url, data=None, headers=None):
        if headers is None:
            headers = {}
        return await request_json(
            self._session,
            method,
            url,
            data=data,
            headers=headers,
            allow_redirects=False,
            label="Pocztex",
            log_401_as_info=True,
            error_with_text=True,
        )

    def _parse_login_form(self, html_text):
        action = ""
        match = re.search(r"<form[^>]*action=[\"\\']([^\"\\']+)[\"\\']", html_text, re.IGNORECASE)
        if match:
            action = html.unescape(match.group(1))
        if not action:
            alt = re.search(
                r"/realms/[^\"\\']+/login-actions/authenticate[^\"\\']*",
                html_text,
                re.IGNORECASE,
            )
            if alt:
                action = html.unescape(alt.group(0))
        hidden_inputs = {}
        for match in re.finditer(
            r"<input[^>]*type=[\"\\']hidden[\"\\'][^>]*>", html_text, re.IGNORECASE
        ):
            tag = match.group(0)
            name_match = re.search(r"name=[\"\\']([^\"\\']+)[\"\\']", tag, re.IGNORECASE)
            value_match = re.search(r"value=[\"\\']([^\"\\']*)[\"\\']", tag, re.IGNORECASE)
            if name_match:
                hidden_inputs[name_match.group(1)] = (
                    html.unescape(value_match.group(1)) if value_match else ""
                )
        return action, hidden_inputs

    async def _get_authorization_code(self, email, password):
        state = secrets.token_hex(16)
        auth_url = self._authorize_url(state)
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": self.LOGIN_ACCEPT_LANGUAGE,
            "User-Agent": self.LOGIN_USER_AGENT,
        }

        async with self._session.get(auth_url, headers=headers, allow_redirects=False) as resp:
            auth_html = await resp.text()
            if resp.status >= 400:
                raise Exception(f"Pocztex login page error: {resp.status}")
            action, hidden_inputs = self._parse_login_form(auth_html)
            if not action:
                raise Exception("Pocztex login form action not found")
            post_url = urllib.parse.urljoin(str(resp.url), action)

        form = {**hidden_inputs}
        form.setdefault("credentialId", "")
        form["username"] = email
        form["password"] = password
        form.setdefault("login", "Log in")

        post_headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": self.LOGIN_ACCEPT_LANGUAGE,
            "Referer": auth_url,
            "Origin": self.LOGIN_ORIGIN,
            "User-Agent": self.LOGIN_USER_AGENT,
        }

        async with self._session.post(
            post_url, data=form, headers=post_headers, allow_redirects=False
        ) as resp:
            location = resp.headers.get("Location")
            if location:
                resolved = urllib.parse.urljoin(str(resp.url), location)
                if resolved.startswith("pocztex://"):
                    return self._extract_code(resolved)

                async with self._session.get(
                    resolved, headers=headers, allow_redirects=False
                ) as next_resp:
                    next_location = next_resp.headers.get("Location")
                    if next_location:
                        next_resolved = urllib.parse.urljoin(
                            str(next_resp.url), next_location
                        )
                        if next_resolved.startswith("pocztex://"):
                            return self._extract_code(next_resolved)

            body = await resp.text()
            snippet = " ".join(body.split())[:500] if body else ""
            raise Exception(
                f"Pocztex login failed. Status {resp.status}. Body: {snippet}"
            )

    def _extract_code(self, redirect_url):
        parsed = urllib.parse.urlparse(redirect_url)
        params = urllib.parse.parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        if not code:
            raise Exception("Pocztex authorization code not found")
        return code

    def _save_token_data(self, data):
        self._token = data.get("access_token")
        self._refresh_token = data.get("refresh_token")
        expires_in = data.get("expires_in")
        refresh_expires_in = data.get("refresh_expires_in")
        now = time.time()
        if expires_in:
            self._expires_at = now + int(expires_in) - 30
        if refresh_expires_in:
            self._refresh_expires_at = now + int(refresh_expires_in) - 30

    async def login(self, email, password):
        code = await self._get_authorization_code(email, password)
        token_data = await self._request_json(
            "POST",
            self._token_url(),
            data={
                "grant_type": "authorization_code",
                "client_id": self.CLIENT_ID,
                "code": code,
                "redirect_uri": self.REDIRECT_URI,
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        self._save_token_data(token_data)
        return token_data

    async def refresh_token(self):
        if not self._refresh_token:
            raise Exception("Missing Pocztex refresh token")
        if self._refresh_expires_at and time.time() > self._refresh_expires_at:
            raise Exception("Pocztex refresh token expired")

        token_data = await self._request_json(
            "POST",
            self._token_url(),
            data={
                "grant_type": "refresh_token",
                "client_id": self.CLIENT_ID,
                "refresh_token": self._refresh_token,
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        self._save_token_data(token_data)
        return token_data

    async def request(self, method, path, params=None):
        # Refresh token if about to expire
        if self._token and self._expires_at and time.time() > self._expires_at - 60:
            await self.refresh_token()

        base = self.API_BASE_URL.rstrip("/")
        url = f"{base}/{path.lstrip('/')}"
        headers = {
            "Accept": "application/json",
            "X-App-Version": self.APP_VERSION,
            "Language": self.LANGUAGE,
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        if params is None:
            params = {}
        if "language" not in params and self.LANGUAGE:
            params["language"] = self.LANGUAGE

        return await request_json(
            self._session,
            method,
            url,
            headers=headers,
            params=params,
            # The tracking backend regularly needs 30s+ to answer authorized
            # queries, so give it more headroom than the default.
            timeout=60,
            label="Pocztex",
            log_401_as_info=False,
            error_with_text=True,
        )

    async def get_parcels(self):
        return await self.request("GET", "/tracking")

    async def get_parcel_details(self, tracking_id):
        if tracking_id is None:
            raise Exception("Missing Pocztex tracking id")
        path = f"/tracking/{urllib.parse.quote(str(tracking_id))}/details"
        return await self.request("GET", path)
