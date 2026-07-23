# WAX210 custom integration for Home Assistant

A native HA integration for NETGEAR WAX210 APs, talking to the AP's own
local LuCI-based web API (no SNMP, no cloud, no HACS `netgear_wax`
integration -- that one targets a different proprietary API your
firmware doesn't run). Confirmed against real WAX210 output, firmware
V1.1.0.36.

## What you get, per AP (added as a separate config entry each)

- `sensor.<name>_connected_clients` -- count, with a `clients` attribute
  listing every associated client (mac, ip, hostname, os, rssi,
  rx_kbytes, tx_kbytes, mode, ssid, band, channel)
- `sensor.<name>_cpu_load` -- %, from the AP's own realtime load endpoint
- `sensor.<name>_memory_load` -- %, computed from memtotal/memavail
- `sensor.<name>_uptime` -- seconds (diagnostic)
- `sensor.<name>_firmware_version` -- scraped from the flashops page (diagnostic)
- `binary_sensor.<name>_network_status` -- the AP's own bridged
  management/LAN interface (there's no true WAN port on this hardware),
  with ipaddr/gwaddr/dns as attributes

## This is a fresh start, not a migration

Per your call: this does NOT try to preserve the old MQTT-published
entities' history. Those lived under the `mqtt` integration; these live
under a new `wax210` integration with entirely different unique_ids, so
HA will create brand-new entities. Once you've confirmed this is
working, go delete the old MQTT-discovered entities/devices from
Settings > Devices & Services > MQTT, and decommission the Pi script
(stop + disable `wax210-monitor.service`).

## Install

1. Copy the `custom_components/wax210/` folder into your HA config
   directory, so you end up with:
   `<config>/custom_components/wax210/__init__.py` (and the rest alongside it)
2. Restart Home Assistant.
3. Settings > Devices & Services > Add Integration > search "WAX210".
4. Enter the AP's IP, username (`admin`), and password. Repeat for the
   second AP as its own separate entry.
5. Optional: click Configure on the integration entry to change the
   poll interval (default 30s).

## Known quirks baked into the login logic (all confirmed the hard way)

- Password is hashed as SHA-512 of `password + "\n"` (like
  `echo "password" | sha512sum`), not the raw password.
- The login POST needs `Origin`/`Referer` headers and an `is_login=1`
  cookie, or the AP returns a bare 403 that looks exactly like a
  brute-force lockout but isn't one.
- Firmware version isn't a JSON endpoint at all -- it's scraped via
  regex from the rendered HTML of the System > Firmware page.

## Not yet built (possible follow-ups)

- Per-client `device_tracker` entities for named/known devices (right
  now the full client list is only available as an attribute on the
  connected-clients sensor, not as individual trackable entities).
- Re-auth flow if the admin password changes after setup (currently
  you'd need to remove and re-add the integration entry).
