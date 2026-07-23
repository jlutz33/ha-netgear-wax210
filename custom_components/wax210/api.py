"""
Synchronous client for a NETGEAR WAX210's local LuCI-based web API.

All of this is confirmed against a real WAX210 (firmware V1.1.0.36) --
see the docstrings on each method for what was actually observed, not
assumed, and why. This class is intentionally synchronous (uses
`requests`); the coordinator is responsible for running its methods in
an executor so they don't block HA's event loop.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from typing import Any, Optional

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_LOGGER = logging.getLogger(__name__)

STOK_RE = re.compile(r";stok=([a-zA-Z0-9]+)/")
FIRMWARE_RE = re.compile(r"var\s+firmwareVersion\s*=\s*'([^']+)'")
SERIAL_RE = re.compile(r'myid="Device_Serial_Number_text">([^<]+)<')
AP_NAME_RE = re.compile(r'repSpecHTML\("([^"]+)"\)')
LAN_MAC_RE = re.compile(r'id="mac_lan"[^>]*>\s*([0-9A-Fa-f:]{17})\s*<')

# wifi0 = 2.4GHz radio, wifi1 = 5GHz radio on this hardware (confirmed
# from channel numbers: 5 vs 177).
DEVICE_BAND = {"wifi0": "2.4GHz", "wifi1": "5GHz"}


class WAX210Error(Exception):
    """Base error for anything that goes wrong talking to the AP."""


class WAX210AuthError(WAX210Error):
    """Raised when login itself fails (bad credentials, unexpected response)."""


class WAX210ConnectionError(WAX210Error):
    """Raised for network-level failures (timeouts, DNS, refused connections)."""


class WAX210Client:
    """Talks to one WAX210's local web UI/API."""

    def __init__(self, host: str, username: str, password: str,
                 verify_ssl: bool = False, timeout: float = 10.0):
        self.host = host
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.session = requests.Session()
        self.stok: Optional[str] = None
        self.base = f"https://{host}"
        self._static_info_cache: Optional[dict] = None

    # -- auth ---------------------------------------------------------

    def login(self) -> None:
        """
        Logs in and captures the stok/sysauth needed for subsequent
        requests. Three things confirmed the hard way while building
        this, all now baked in:

        1. The password is hashed as SHA-512 of (plaintext + "\\n") --
           i.e. the same thing `echo "password" | sha512sum` produces --
           not a hash of the raw password. This is exactly what the
           login page's own JS does:
               f.password.value = sha512sum(f.password_plain_text.value+"\\n");
        2. The login POST needs an Origin header, a Referer header, and
           an `is_login=1` cookie (which the login page's JS sets via
           doCookieSetup("is_login", "1", 1) right before submitting).
           Without these, the AP returns a bare 403 that looks exactly
           like a brute-force lockout but has nothing to do with one.
        3. On success, stok comes back either in the redirect Location
           header (;stok=<token>/...) or as a cookie -- this checks both.
        """
        url = f"{self.base}/cgi-bin/luci"
        body = {
            "username": self.username,
            "password": hashlib.sha512((self.password + "\n").encode("utf-8")).hexdigest(),
            "agree": "1",
            "agree_info": "on",
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": self.base,
            "Referer": url,
        }

        self.session = requests.Session()
        self.session.cookies.set("is_login", "1")

        try:
            resp = self.session.post(
                url, data=body, headers=headers,
                verify=self.verify_ssl, timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as e:
            raise WAX210ConnectionError(f"[{self.host}] connection error during login: {e}") from e

        stok = None
        location = resp.headers.get("Location", "")
        m = STOK_RE.search(location)
        if m:
            stok = m.group(1)
        if not stok:
            for cookie_name in ("stok", "sysauth_stok"):
                if cookie_name in self.session.cookies:
                    stok = self.session.cookies.get(cookie_name)
                    break
        if not stok:
            m = STOK_RE.search(resp.text or "")
            if m:
                stok = m.group(1)

        if resp.status_code not in (200, 302, 303) or not stok:
            raise WAX210AuthError(
                f"[{self.host}] login failed: status={resp.status_code}"
            )
        self.stok = stok

    def _authed_url(self, path: str) -> str:
        assert self.stok, "not logged in"
        return f"{self.base}/cgi-bin/luci/;stok={self.stok}/{path.lstrip('/')}"

    # -- low-level fetch helpers ---------------------------------------

    def _get_json(self, path: str, params: Optional[dict] = None,
                  _retried: bool = False) -> Any:
        if not self.stok:
            self.login()
        url = self._authed_url(path)
        try:
            resp = self.session.get(url, params=params, verify=self.verify_ssl,
                                     timeout=self.timeout)
        except requests.RequestException as e:
            raise WAX210ConnectionError(f"[{self.host}] request error on {path}: {e}") from e

        if resp.status_code != 200:
            if not _retried:
                self.stok = None
                self.login()
                return self._get_json(path, params=params, _retried=True)
            raise WAX210ConnectionError(f"[{self.host}] {path} returned {resp.status_code} after re-login")

        try:
            return resp.json()
        except ValueError:
            if not _retried:
                self.stok = None
                self.login()
                return self._get_json(path, params=params, _retried=True)
            raise WAX210ConnectionError(f"[{self.host}] {path} did not return JSON after re-login")

    def _get_text(self, path: str, params: Optional[dict] = None,
                  _retried: bool = False) -> str:
        if not self.stok:
            self.login()
        url = self._authed_url(path)
        try:
            resp = self.session.get(url, params=params, verify=self.verify_ssl,
                                     timeout=self.timeout)
        except requests.RequestException as e:
            raise WAX210ConnectionError(f"[{self.host}] request error on {path}: {e}") from e

        if resp.status_code != 200:
            if not _retried:
                self.stok = None
                self.login()
                return self._get_text(path, params=params, _retried=True)
            raise WAX210ConnectionError(f"[{self.host}] {path} returned {resp.status_code} after re-login")
        return resp.text

    # -- endpoint-specific parsing ---------------------------------------

    @staticmethod
    def _parse_kb_string(value: Any) -> Optional[int]:
        """Parses '144727Kb' style strings into an int (KB)."""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return int(value)
        m = re.match(r"^\s*(\d+)", str(value))
        return int(m.group(1)) if m else None

    @staticmethod
    def _walk_assoclists(node: Any, ctx: dict) -> list:
        """
        Recursively finds every 'assoclist' anywhere in the overview
        response. Confirmed shape on V1.1.0.36: assoclist is a dict
        keyed by client MAC (e.g. {"18:7f:88:8f:2b:47": {"rssi": "-44",
        ...}}), tagged here with whatever ssid/ifname/device/channel
        context is available at that nesting level (also accepts a
        list-of-dicts shape defensively, in case a different firmware
        build differs).
        """
        results = []
        if isinstance(node, dict):
            local_ctx = dict(ctx)
            for key in ("ssid", "ifname", "device", "channel"):
                if key in node and isinstance(node[key], (str, int)):
                    local_ctx[key] = node[key]
            assoc = node.get("assoclist")
            if isinstance(assoc, dict):
                for mac, entry in assoc.items():
                    if isinstance(entry, dict):
                        results.append({**local_ctx, "mac": mac, **entry})
            elif isinstance(assoc, list):
                for entry in assoc:
                    if isinstance(entry, dict):
                        results.append({**local_ctx, **entry})
            for k, v in node.items():
                if k == "assoclist":
                    continue
                results.extend(WAX210Client._walk_assoclists(v, local_ctx))
        elif isinstance(node, list):
            for item in node:
                results.extend(WAX210Client._walk_assoclists(item, ctx))
        return results

    def get_overview(self) -> dict:
        return self._get_json("admin/status/overview", params={"status": "1"})

    def get_sysinfo(self) -> dict:
        """
        Confirmed shape (status=2) on V1.1.0.36:
        {"memavail": 272412, "uptime": 86493, "memcached": 53488,
         "memtotal": 491200, "localtime": "...", "membuffers": 13856,
         "memfree": 216704}
        mem* fields are in KB; uptime is already plain seconds.
        """
        return self._get_json("admin/status/overview", params={"status": "2"})

    def get_load_status(self) -> list:
        """
        Confirmed shape on V1.1.0.36: a JSON array of
        [timestamp, load1, load5, load15] rows, all three columns
        identical (a single instantaneous % sample, not true rolling
        averages), already a plain percentage.
        """
        return self._get_json(
            "admin/status/realtime/load_status",
            params={"_": str(time.time())},
        )

    def get_device_static_info(self) -> dict:
        """
        Confirmed on V1.1.0.36: the plain admin/status/overview page
        (fetched with NO ?status= query param -- a different fetch
        entirely from the JSON status=1/status=2 variants used elsewhere
        in this file) renders full HTML embedding firmware version,
        serial number, and AP name directly in the page/inline JS, not
        as JSON:
            var firmwareVersion = '1.1.0.36';
            <td myid="Device_Serial_Number_text">7J31492BA0990</td>
            var SystemName = repSpecHTML("NETGEARD9D155");document.write(SystemName);
        (Firmware was previously scraped from admin/system/flashops --
        moved here since it's the same value available from a page we
        may as well also use for serial/name, one fetch instead of two.)

        These three values are effectively static per AP (serial number
        and AP name never change; firmware only changes on an upgrade,
        which is itself a rare, restart-worthy event) so this is fetched
        once per WAX210Client instance and cached, rather than re-fetched
        every poll cycle alongside the genuinely dynamic data.
        """
        if self._static_info_cache is not None:
            return self._static_info_cache

        html = self._get_text("admin/status/overview")

        firmware = None
        m = FIRMWARE_RE.search(html)
        if m:
            firmware = m.group(1)

        serial_number = None
        m = SERIAL_RE.search(html)
        if m:
            serial_number = m.group(1)

        ap_name = None
        m = AP_NAME_RE.search(html)
        if m:
            ap_name = m.group(1)

        lan_mac = None
        m = LAN_MAC_RE.search(html)
        if m:
            lan_mac = m.group(1).lower()

        info = {"firmware": firmware, "serial_number": serial_number, "ap_name": ap_name, "lan_mac": lan_mac}
        self._static_info_cache = info
        return info

    def get_client_info(self) -> dict:
        """mac (lowercased) -> {ip, os, hostname}"""
        data = self._get_json("admin/status/clientInfo")
        out = {}
        for line in (data or {}).get("info", []):
            parts = line.split("|")
            if len(parts) < 4:
                continue
            mac, ip, os_name, hostname = parts[0], parts[1], parts[2], parts[3]
            out[mac.lower()] = {"ip": ip, "os": os_name, "hostname": hostname}
        return out

    # -- the one method the coordinator actually calls ------------------

    def get_all_data(self) -> dict:
        """
        One call that gathers everything the coordinator needs for a
        poll cycle: client list, WAN/management-interface info, and
        system diagnostics (uptime/mem/cpu/firmware). Raises
        WAX210AuthError / WAX210ConnectionError on failure; the
        coordinator translates those into UpdateFailed.
        """
        overview = self.get_overview()
        clients_info = self.get_client_info()
        assoc = self._walk_assoclists(overview, {})

        clients = []
        for entry in assoc:
            mac = str(entry.get("mac", "")).lower()
            if not mac:
                continue
            info = clients_info.get(mac, {})
            rssi_raw = entry.get("rssi")
            try:
                rssi = int(rssi_raw) if rssi_raw is not None else None
            except (TypeError, ValueError):
                rssi = None
            clients.append({
                "mac": mac,
                "ip": info.get("ip"),
                "os": info.get("os"),
                "hostname": info.get("hostname"),
                "rssi": rssi,
                "rx_kbytes": self._parse_kb_string(entry.get("rx_bytes")),
                "tx_kbytes": self._parse_kb_string(entry.get("tx_bytes")),
                "mode": entry.get("MODE") or entry.get("mode"),
                "ssid": entry.get("ssid"),
                "channel": entry.get("channel"),
                "band": DEVICE_BAND.get(entry.get("device"), entry.get("device")),
            })

        # 'wan' in the API response is actually the AP's own bridged
        # management/LAN interface (ifname br-lan), not a router-style
        # WAN link -- expected, since the WAX210 has no WAN port. There's
        # no explicit up/down flag, so infer it from having a real IP and
        # non-zero uptime.
        wan = overview.get("wan") or {}
        ip = wan.get("ipaddr")
        try:
            wan_uptime = float(wan.get("uptime") or 0)
        except (TypeError, ValueError):
            wan_uptime = 0
        network_up = bool(ip) and ip != "0.0.0.0" and wan_uptime > 0

        sysinfo = self.get_sysinfo()
        uptime_s = sysinfo.get("uptime")
        memtotal = sysinfo.get("memtotal")
        memavail = sysinfo.get("memavail")
        mem_pct = None
        if memtotal and memavail is not None and memtotal > 0:
            mem_pct = round((memtotal - memavail) / memtotal * 100, 1)

        cpu_pct = None
        load_rows = self.get_load_status()
        if load_rows:
            last_row = load_rows[-1]
            if len(last_row) > 1:
                cpu_pct = last_row[1]

        radio_channels: dict[str, Optional[int]] = {}
        for wifinet in overview.get("wifinets", []):
            band = DEVICE_BAND.get(wifinet.get("device", ""))
            if band:
                try:
                    radio_channels[band] = int(wifinet["channel"])
                except (KeyError, TypeError, ValueError):
                    radio_channels[band] = None

        total_rx = sum(c["rx_kbytes"] for c in clients if c.get("rx_kbytes") is not None)
        total_tx = sum(c["tx_kbytes"] for c in clients if c.get("tx_kbytes") is not None)

        firmware_info = self.get_device_static_info()

        return {
            "clients": clients,
            "client_count": len(clients),
            "macs_seen": {c["mac"] for c in clients},
            "network_up": network_up,
            "network_info": wan,
            "uptime_s": uptime_s,
            "mem_pct": mem_pct,
            "cpu_pct": cpu_pct,
            "channel_2_4ghz": radio_channels.get("2.4GHz"),
            "channel_5ghz": radio_channels.get("5GHz"),
            "total_rx_kbytes": total_rx,
            "total_tx_kbytes": total_tx,
            "firmware": firmware_info.get("firmware"),
            "serial_number": firmware_info.get("serial_number"),
            "ap_name": firmware_info.get("ap_name"),
            "lan_mac": firmware_info.get("lan_mac"),
        }
