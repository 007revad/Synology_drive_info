#!/usr/bin/env python
"""
Synology NAS discovery via findhostd UDP broadcast (port 9999).
Compatible with Python 2 (DSM 6) and Python 3 (DSM 7).

Uses the syno_finder plaintext protocol (magic 0x12345678_SYNO).
On Windows requires binding to UDP port 9999 to receive responses.

Usage:
    python syno_discover.py
    python syno_discover.py --timeout 5
    python syno_discover.py --json
"""

from __future__ import print_function
import socket
import struct
import sys
import os
import re
import json

# ---------------------------------------------------------------------------
# Protocol constants
# ---------------------------------------------------------------------------
MAGIC        = b'\x12\x34\x56\x78\x53\x59\x4e\x4f'
BCAST_PORT   = 9999
BCAST_ADDR   = '255.255.255.255'
DEFAULT_TIMEOUT = 3

# Default location of Drive Info's settings.conf on the local NAS. Manually
# added NAS entries here take priority over discovered IPs for the same
# hostname (e.g. if the admin has pinned a specific interface/IP to use).
#
# DSM 7: var/ exists and is writable by drive_info (run-as: package)
# DSM 6: var/ doesn't exist; settings live in etc/ instead
# Mirrors the same check api.cgi uses ([[ -d "${PKG_ROOT}/var" ]]), so the
# two always agree without needing to parse /etc.defaults/VERSION.
_PKG_ROOT = '/var/packages/drive_info'
if os.path.isdir(os.path.join(_PKG_ROOT, 'var')):
    DEFAULT_SETTINGS_PATH = os.path.join(_PKG_ROOT, 'var', 'settings.conf')
else:
    DEFAULT_SETTINGS_PATH = os.path.join(_PKG_ROOT, 'etc', 'settings.conf')

# Non-Synology MAC to use in 0x7c fields - findhostd ignores queries
# from Synology OUI MACs (00:11:32, 90:09:d0). VMware OUI works fine.
VMWARE_MAC   = b'00:50:56:c0:00:08'

# TLV pkt_ids (response fields we care about)
PKT_MAC        = 0x19  # NAS MAC address (17-byte ASCII)
PKT_IP         = 0x12  # NAS IP address (4 bytes big-endian)
PKT_HOSTNAME   = 0x11  # NAS hostname (ASCII string)
PKT_HTTP_PORT  = 0x75  # DSM HTTP port (4 bytes little-endian)
PKT_HTTPS_PORT = 0x76  # DSM HTTPS port (4 bytes little-endian)
PKT_DSM_BUILD  = 0x49  # DSM build number (4 bytes little-endian)
PKT_DSM_VER    = 0x77  # DSM version string (e.g. "7.3.2")
PKT_MODEL      = 0x78  # NAS model (e.g. "DS1821+")
PKT_PLATFORM   = 0x70  # Platform/codename
PKT_SERIAL     = 0xc0  # Serial number (ASCII string)


def make_tlv(pkt_id, data):
    """Build a TLV: 1-byte id + 1-byte length + data bytes."""
    length = min(len(data), 0xff)
    if sys.version_info[0] >= 3:
        return bytes([pkt_id, length]) + data[:length]
    else:
        return chr(pkt_id) + chr(length) + data[:length]


def build_query():
    """
    Build the plaintext discovery query packet.

    Key findings from Wireshark reverse engineering:
    - Packet type 0x01 field must be \x00\x00\x00\x01 (not \x00\x00\x00\x00)
    - Must include four 0x7c MAC fields
    - MAC in 0x7c must be a non-Synology OUI or findhostd ignores it
    - Synology Assistant sends pkt1 (type=0x00) then pkt2 (type=0x01);
      NAS only respond to pkt2
    """
    pkt  = MAGIC
    pkt += make_tlv(0xa4, b'\x00\x00\x02\x01')
    pkt += make_tlv(0xa6, b'\x78\x00\x00\x00')
    pkt += make_tlv(0x01, b'\x01\x00\x00\x00')   # type=1, little-endian
    pkt += make_tlv(0xb0, b'\xc0\x01\x00\x00\x00\x00\x00\x00')
    pkt += make_tlv(0xb1, b'\x00\x00\x00\x00\x00\x00\x00\x00')
    pkt += make_tlv(0xb8, b'\xc0\x01\x00\x00\x00\x00\x00\x00')
    pkt += make_tlv(0xb9, b'\x00\x00\x00\x00\x00\x00\x00\x00')
    pkt += make_tlv(0x7c, VMWARE_MAC)
    pkt += make_tlv(0x7c, VMWARE_MAC)
    pkt += make_tlv(0x7c, VMWARE_MAC)
    pkt += make_tlv(0x7c, VMWARE_MAC)
    return pkt


def parse_response(data):
    """
    Parse a findhostd plaintext response packet.
    Returns a dict of fields, or None if the magic is wrong.
    """
    if len(data) < 8:
        return None
    if data[:8] != MAGIC:
        return None

    result = {}
    pos = 8
    while pos + 1 < len(data):
        if sys.version_info[0] >= 3:
            pkt_id = data[pos]
            length = data[pos + 1]
        else:
            pkt_id = ord(data[pos])
            length = ord(data[pos + 1])
        pos += 2
        if pos + length > len(data):
            break
        value = data[pos:pos + length]
        pos += length

        if pkt_id == PKT_HOSTNAME:
            result['hostname'] = value.decode('utf-8', errors='replace')

        elif pkt_id == PKT_MAC:
            result['mac'] = value.decode('ascii', errors='replace')

        elif pkt_id == PKT_IP:
            if len(value) == 4:
                if sys.version_info[0] >= 3:
                    result['ip'] = '%d.%d.%d.%d' % (
                        value[0], value[1], value[2], value[3])
                else:
                    result['ip'] = '%d.%d.%d.%d' % (
                        ord(value[0]), ord(value[1]),
                        ord(value[2]), ord(value[3]))

        elif pkt_id == PKT_HTTP_PORT:
            if len(value) == 4:
                result['http_port'] = struct.unpack('<I', value)[0]

        elif pkt_id == PKT_HTTPS_PORT:
            if len(value) == 4:
                result['https_port'] = struct.unpack('<I', value)[0]

        elif pkt_id == PKT_DSM_VER:
            # Strip trailing non-printable bytes (e.g. 0x90 build separator)
            ver = value.decode('ascii', errors='replace')
            if sys.version_info[0] >= 3:
                result['dsm_version'] = ''.join(
                    c for c in ver if c.isprintable() and ord(c) < 128)
            else:
                result['dsm_version'] = ''.join(
                    c for c in ver if 0x20 <= ord(c) < 0x80)

        elif pkt_id == PKT_DSM_BUILD:
            if len(value) == 4:
                result['dsm_build'] = struct.unpack('<I', value)[0]

        elif pkt_id == PKT_MODEL:
            result['model'] = value.decode('utf-8', errors='replace')

        elif pkt_id == PKT_PLATFORM:
            result['platform'] = value.decode('utf-8', errors='replace')

        elif pkt_id == PKT_SERIAL:
            result['serial'] = value.decode('ascii', errors='replace')

    return result if result else None


def format_ip_group(ips):
    """
    Format a list of IPs belonging to one NAS (multiple LAN ports) into a
    compact display string.

    If all IPs share the same /24 (first three octets), collapse to
    'a.b.c.d/e/f' style, e.g. ['192.168.20.200', '192.168.20.202'] ->
    '192.168.20.200/202'. Otherwise (different subnets - e.g. LAN ports on
    separate VLANs) just comma-join the full IPs.
    """
    # De-dup while preserving order
    seen = set()
    uniq = []
    for ip in ips:
        if ip not in seen:
            seen.add(ip)
            uniq.append(ip)

    if len(uniq) <= 1:
        return uniq[0] if uniq else ''

    octets = [ip.split('.') for ip in uniq]
    if all(len(o) == 4 for o in octets) and \
       all(o[:3] == octets[0][:3] for o in octets):
        return octets[0][0] + '.' + octets[0][1] + '.' + octets[0][2] + \
            '.' + '/'.join(o[3] for o in octets)

    return ', '.join(uniq)


def read_manual_nas_overrides(settings_path):
    """
    Read manually-added NAS entries from Drive Info's settings.conf and
    return a dict of {hostname_lower: ip} for entries that are enabled.

    Expected line format (shell-style assignment), e.g.:
        manual_nas_count="1"
        manual_nas2="Oscar,192.168.20.200,5000,1,5001"

    Each manual_nasN value is comma-separated:
        name, ip, http_port, enabled(1/0), https_port

    manual_nasN suffixes are treated as persistent IDs that may have gaps
    (e.g. an entry was deleted), so every manual_nasN key present is read
    rather than assuming a contiguous 1..count range.
    """
    overrides = {}
    if not settings_path or not os.path.isfile(settings_path):
        return overrides

    try:
        with open(settings_path, 'r') as f:
            content = f.read()
    except Exception as e:
        sys.stderr.write('WARNING: Could not read %s: %s\n' % (settings_path, e))
        return overrides

    for match in re.finditer(r'manual_nas\d+="([^"]*)"', content):
        fields = match.group(1).split(',')
        if len(fields) < 5:
            continue
        name, ip, http_port, enabled, https_port = fields[:5]
        if enabled.strip() != '1':
            continue
        if not name or not ip:
            continue
        overrides[name.strip().lower()] = ip.strip()

    return overrides


def _broadcast_addrs_ioctl():
    """
    Return the IPv4 broadcast address of every up interface that has one,
    e.g. ['192.168.12.255'].

    Sending only to 255.255.255.255 works on a NAS with one network port,
    but on a router (SRM) that packet leaves by the default route, which
    is the internet side, so the LAN never sees it. Sending to each
    interface's own broadcast address makes the kernel use that interface.
    Works on Python 2 and 3. Returns [] if it cannot be worked out.
    """
    addrs = []
    try:
        import array
        import fcntl
        SIOCGIFCONF = 0x8912
        SIOCGIFFLAGS = 0x8913
        SIOCGIFBRDADDR = 0x8919
        IFF_UP = 0x1
        IFF_BROADCAST = 0x2
        # struct ifreq is 40 bytes on 64-bit and 32 bytes on 32-bit
        ifreq_size = 40 if struct.calcsize('P') == 8 else 32
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            buf = array.array('B', b'\0' * (ifreq_size * 64))
            addr, length = buf.buffer_info()
            res = fcntl.ioctl(s.fileno(), SIOCGIFCONF,
                              struct.pack('iL', ifreq_size * 64, addr))
            out_len = struct.unpack('iL', res)[0]
            raw = buf.tobytes() if hasattr(buf, 'tobytes') else buf.tostring()
            for i in range(0, out_len, ifreq_size):
                name = raw[i:i + 16].split(b'\0', 1)[0]
                if not name:
                    continue
                try:
                    ifr = struct.pack('256s', name[:15])
                    flags = struct.unpack(
                        'H', fcntl.ioctl(s.fileno(), SIOCGIFFLAGS, ifr)[16:18])[0]
                    if not (flags & IFF_UP) or not (flags & IFF_BROADCAST):
                        continue
                    brd = socket.inet_ntoa(
                        fcntl.ioctl(s.fileno(), SIOCGIFBRDADDR, ifr)[20:24])
                except Exception:
                    continue
                if brd and brd != '0.0.0.0' and brd not in addrs:
                    addrs.append(brd)
        finally:
            s.close()
    except Exception:
        return []
    return addrs


def _broadcast_addrs_from_route(route_text):
    """
    Work out broadcast addresses from the contents of /proc/net/route:
    for every directly connected network (no gateway) the broadcast
    address is the network address with all host bits set. Needs no
    ioctl, so it is the fallback when _broadcast_addrs_ioctl() finds
    nothing.
    """
    addrs = []
    for line in route_text.splitlines()[1:]:
        f = line.split()
        if len(f) < 8:
            continue
        try:
            dest = int(f[1], 16)
            gw = int(f[2], 16)
            flags = int(f[3], 16)
            mask = int(f[7], 16)
        except ValueError:
            continue
        # Skip down routes, default route, gateway routes and /32 host routes
        if not (flags & 0x1) or dest == 0 or mask == 0 or gw != 0:
            continue
        if mask == 0xFFFFFFFF:
            continue
        brd = (dest | (~mask & 0xFFFFFFFF)) & 0xFFFFFFFF
        # /proc/net/route prints the address in host byte order
        brd_str = socket.inet_ntoa(struct.pack('=L', brd))
        if brd_str not in addrs:
            addrs.append(brd_str)
    return addrs


def _is_private_ipv4(addr):
    """True for 10/8, 172.16/12, 192.168/16 and 169.254/16 addresses."""
    try:
        o = [int(x) for x in addr.split('.')]
    except ValueError:
        return False
    if len(o) != 4:
        return False
    return (o[0] == 10 or
            (o[0] == 172 and 16 <= o[1] <= 31) or
            (o[0] == 192 and o[1] == 168) or
            (o[0] == 169 and o[1] == 254))


def get_broadcast_addrs():
    """
    Return the IPv4 broadcast address of each directly connected network,
    e.g. ['192.168.12.255'], from both the interface list and the routing
    table. Returns [] if neither works.
    """
    addrs = _broadcast_addrs_ioctl()
    try:
        with open('/proc/net/route', 'r') as f:
            route_addrs = _broadcast_addrs_from_route(f.read())
    except Exception:
        route_addrs = []
    for a in route_addrs:
        if a not in addrs:
            addrs.append(a)
    # Only broadcast on private LAN networks, never towards the internet
    return [a for a in addrs if _is_private_ipv4(a)]


def discover(timeout=DEFAULT_TIMEOUT, settings_path=DEFAULT_SETTINGS_PATH):
    """
    Broadcast a discovery query and collect responses.
    Returns a list of dicts, one per responding NAS.
    Deduplicates by MAC address (each NAS sends 2 responses).
    """
    query = build_query()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        sock.bind(('0.0.0.0', BCAST_PORT))
    except Exception as e:
        sys.stderr.write('WARNING: Could not bind to port %d: %s\n' % (BCAST_PORT, e))
        try:
            sock.bind(('0.0.0.0', 0))  # random port - may still work on Linux
            sys.stderr.write('WARNING: Bound to random port instead.\n')
        except Exception:
            pass

    sock.settimeout(timeout)

    # Always send to the limited broadcast address (what a NAS has always
    # used), then also to each interface's own broadcast address so the
    # query reaches the LAN on a router with several interfaces.
    sent = False
    for target in [BCAST_ADDR] + get_broadcast_addrs():
        try:
            sock.sendto(query, (target, BCAST_PORT))
            sent = True
        except Exception as e:
            sys.stderr.write('WARNING: Failed to send broadcast to %s: %s\n' % (target, e))
    if not sent:
        sys.stderr.write('ERROR: Failed to send broadcast\n')
        sock.close()
        return []

    # Group by hostname, collecting every IP seen for that NAS (a unit with
    # multiple LAN ports / PCIe LAN cards answers once per interface).
    # Entries with no hostname fall back to being grouped by MAC instead.
    host_groups = {}   # hostname_lower -> {'entry': parsed dict, 'ips': [...], 'macs': set()}
    mac_groups = {}    # mac -> {'entry': parsed dict, 'ips': [...]}

    while True:
        try:
            data, addr = sock.recvfrom(4096)
        except socket.timeout:
            break
        except Exception as e:
            sys.stderr.write('WARNING: recvfrom error: %s\n' % e)
            break

        parsed = parse_response(data)
        if parsed is None:
            continue

        # Use source IP from UDP packet if not in payload
        if 'ip' not in parsed:
            parsed['ip'] = addr[0]

        # Deduplicate - each NAS sends 2 responses (broadcast + unicast),
        # and a NAS with multiple LAN ports configured (multiple IPs/MACs)
        # will answer once per interface. Prefer hostname as the dedup key
        # since it's stable across a NAS's interfaces; fall back to MAC
        # for the rare case a response has no hostname.
        hostname = parsed.get('hostname')
        if hostname:
            key = hostname.lower()
            group = host_groups.setdefault(
                key, {'entry': parsed, 'ips': [], 'macs': set()})
            group['ips'].append(parsed['ip'])
            mac = parsed.get('mac')
            if mac:
                group['macs'].add(mac)
        else:
            mac = parsed.get('mac', addr[0])
            group = mac_groups.setdefault(mac, {'entry': parsed, 'ips': []})
            group['ips'].append(parsed['ip'])

    sock.close()

    overrides = read_manual_nas_overrides(settings_path)

    results = []
    for group in list(host_groups.values()) + list(mac_groups.values()):
        entry = dict(group['entry'])  # copy, keep first-seen field values
        entry.setdefault('http_port', 5000)
        entry.setdefault('https_port', 5001)

        entry['ips'] = group['ips']  # full list, for callers that want it
        # 'ip' MUST stay a single connectable address - it's used to build
        # URLs for reaching the NAS's api.cgi. 'ip_display' is the merged/
        # compact string (e.g. '192.168.20.200/202') for showing in the UI
        # only - never use it to connect to anything.
        entry['ip'] = group['ips'][0]
        entry['ip_display'] = format_ip_group(group['ips'])

        hostname = entry.get('hostname')
        if hostname:
            manual_ip = overrides.get(hostname.lower())
            if manual_ip:
                entry['ip'] = manual_ip
                entry['ip_display'] = manual_ip
                entry['ip_source'] = 'manual'
            else:
                entry['ip_source'] = 'discovered'

        results.append(entry)

    # Sort by connectable IP for consistent output
    results.sort(key=lambda x: tuple(
        int(o) for o in x['ip'].split('.')) if x.get('ip') else (0, 0, 0, 0))
    return results


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description='Discover Synology NAS on local network.')
    parser.add_argument('--timeout', type=int, default=DEFAULT_TIMEOUT,
                        help='Seconds to wait for responses (default: %d)' % DEFAULT_TIMEOUT)
    parser.add_argument('--json', action='store_true',
                        help='Output as JSON')
    parser.add_argument('--settings-path', default=DEFAULT_SETTINGS_PATH,
                        help='Path to Drive Info settings.conf for manual '
                             'NAS IP overrides (default: %s)' % DEFAULT_SETTINGS_PATH)
    args = parser.parse_args()

    nas_list = discover(timeout=args.timeout, settings_path=args.settings_path)

    if args.json:
        print(json.dumps(nas_list, indent=2))
        return

    if not nas_list:
        print('No Synology NAS found.')
        return

    print('Found %d Synology NAS:\n' % len(nas_list))
    #fmt = '%-20s %-17s %-16s %-6s %-6s %s'
    #fmt = '%-12s %-19s %-15s %-5s %-5s %s'
    fmt = '%-15s %-19s %-24s %-6s %-6s %s'
    print(fmt % ('Hostname', 'MAC', 'IP', 'HTTP', 'HTTPS', 'Model'))
    print('' + '-' * 79)
    for nas in nas_list:
        print(fmt % (
            nas.get('hostname', '?'),
            nas.get('mac', '?'),
            nas.get('ip_display', nas.get('ip', '?')),
            nas.get('http_port', '?'),
            nas.get('https_port', '?'),
            nas.get('model', '?'),
        ))
        #if 'dsm_version' in nas:
        #    build = nas.get('dsm_build', '')
        #    print('  %s DSM %s%s' % (
        #        ' ' * 20,
        #        nas['dsm_version'],
        #        (' build %s' % build) if build else ''
        #    ))
    print()


if __name__ == '__main__':
    main()
