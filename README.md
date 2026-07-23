# WAX210 custom integration for Home Assistant

A native HA integration for NETGEAR WAX210 APs, talking to the AP's own
local LuCI-based web API (no SNMP, no cloud, no HACS `netgear_wax`
integration -- that one targets a different proprietary API your
firmware doesn't run). Confirmed against real WAX210 output, firmware
V1.1.0.36.

## What you get

### Per AP (each AP is added as its own config entry)

- `sensor.<name>_connected_clients` -- count, with a `clients` attribute
  listing every associated client (mac, ip, hostname, os, rssi,
  rx_kbytes, tx_kbytes, mode, ssid, band, channel)
- `sensor.<name>_cpu_load` -- %, from the AP's own realtime load endpoint
- `sensor.<name>_memory_load` -- %, computed from memtotal/memavail
- `sensor.<name>_last_boot` -- timestamp (diagnostic)
- `sensor.<name>_uptime_seconds` -- seconds (diagnostic)
- `binary_sensor.<name>_network_status` -- the AP's own bridged
  management/LAN interface (there's no true WAN port on this hardware),
  with ipaddr/gwaddr/dns as attributes

### Per WiFi client (shared across all APs)

- `device_tracker.<hostname_or_mac>` -- one entity per MAC address seen,
  `home` if the device is connected to **any** configured WAX210 AP,
  `not_home` otherwise. Attributes: `os`, `rssi`, `rx_kbytes`,
  `tx_kbytes`, `mode`, `ssid`, `band`, `channel`, and `ap` (which AP
  it's currently on).

  Entities are created dynamically the first time a device is seen and
  persist in the HA entity registry after it disconnects. With multiple
  APs configured, a device roaming between them stays `home` the whole
  time -- there is only one tracker entity per MAC, not one per AP.

  To use these for presence detection, go to Settings > People, edit a
  person, and link their phone's tracker entity to that person.

## Install

### Manual

1. Copy the `custom_components/wax210/` folder into your HA config
   directory, so you end up with:
   `<config>/custom_components/wax210/__init__.py` (and the rest alongside it)
2. Restart Home Assistant.
3. Settings > Devices & Services > Add Integration > search "WAX210".
4. Enter the AP's IP, username (`admin`), and password. Repeat for each
   additional AP as its own separate entry.
5. Optional: click Configure on the integration entry to change the
   poll interval (default 30s).

### HACS (custom repository)

1. In HACS, go to Integrations > ⋮ > Custom repositories.
2. Add `https://github.com/jlutz33/ha-netgear-wax210` with category **Integration**.
3. Install "NETGEAR WAX210" from the HACS store, then restart HA.
4. Follow steps 3-5 above.

## Known quirks baked into the login logic (all confirmed the hard way)

- Password is hashed as SHA-512 of `password + "\n"` (like
  `echo "password" | sha512sum`), not the raw password.
- The login POST needs `Origin`/`Referer` headers and an `is_login=1`
  cookie, or the AP returns a bare 403 that looks exactly like a
  brute-force lockout but isn't one.
- Firmware version isn't a JSON endpoint at all -- it's scraped via
  regex from the rendered HTML of the System > Firmware page.

## Not yet built (possible follow-ups)

- Re-auth flow if the admin password changes after setup (currently
  you'd need to remove and re-add the integration entry).
