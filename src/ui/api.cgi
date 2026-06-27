#!/bin/bash

PKG_NAME="drive_info"
PKG_ROOT="/var/packages/${PKG_NAME}"
TARGET_DIR="${PKG_ROOT}/target"
SCRIPT="${TARGET_DIR}/ui/bin/drive_info.sh"
SUDOERS_FILE="/etc/sudoers.d/${PKG_NAME}"

# shellcheck source=ui/modules/get_text.sh
source "${TARGET_DIR}/ui/modules/get_text.sh"

# ---------------------------------------------------------------------------
# Settings file location
# DSM 7: var/ exists and is writable by drive_info (run-as: package)
# DSM 6: var/ doesn't exist; use etc/ (chmod 666 set in postinst)
# ---------------------------------------------------------------------------
if [[ -d "${PKG_ROOT}/var" ]]; then
    SETTINGS_CONF="${PKG_ROOT}/var/settings.conf"
else
    SETTINGS_CONF="${PKG_ROOT}/etc/settings.conf"
fi

# ---------------------------------------------------------------------------
# JSON API actions - handled before any HTML output
# ---------------------------------------------------------------------------

# Parse action from QUERY_STRING
_action=""
if [[ "${QUERY_STRING:-}" =~ (^|&)action=([^&]*) ]]; then
    _action="${BASH_REMATCH[2]}"
fi

# ---------------------------------------------------------------------------
# action=info
# Returns JSON identifying this NAS. No sudo needed.
# Used by remote NAS fetch so the frontend knows who responded.
# ---------------------------------------------------------------------------
if [[ "$_action" == "info" ]]; then
    _hostname=$(cat /proc/sys/kernel/hostname 2>/dev/null || hostname)
    #_model=$(cat /proc/sys/kernel/syno_hw_version 2>/dev/null || echo "")
    _version=$(grep -m1 'productversion=' /etc.defaults/VERSION 2>/dev/null \
                | cut -d= -f2 | tr -d '"')

    _model=$(synogetkeyvalue /etc.defaults/synoinfo.conf upnpmodelname 2>/dev/null)
    # Fallback for systems where upnpmodelname is unavailable
    if [[ -z "$_model" && -f /proc/sys/kernel/syno_hw_version ]]; then
        _model=$(cat /proc/sys/kernel/syno_hw_version 2>/dev/null || echo "")
        # Check for dodgy characters after model number
        if [[ ${_model,,} =~ 'pv10-j'$ ]]; then  # GitHub issue #10
            _model=${_model%??????}+             # replace last 6 chars with +
        elif [[ ${_model} =~ '-j'$ ]]; then  # GitHub issue #2
            _model=${_model%??}              # remove last 2 chars
        fi
    fi
    if [[ -z "$_model" ]]; then
        _model="Unknown_model"
    fi

    printf 'Content-Type: application/json\r\n'
    printf 'Access-Control-Allow-Origin: *\r\n'
    printf '\r\n'
    printf '{"hostname":"%s","model":"%s","dsm_version":"%s"}\n' \
        "$_hostname" "$_model" "$_version"
    exit 0
fi

# ---------------------------------------------------------------------------
# action=discover
# Runs syno_discover.py and streams the JSON NAS list.
# Returns the other NAS on the LAN (the local NAS is not included in the
# findhostd responses - the frontend adds it separately via action=info).
# ---------------------------------------------------------------------------
if [[ "$_action" == "discover" ]]; then
    DISCOVER_SCRIPT="${TARGET_DIR}/ui/bin/syno_discover.py"
    printf 'Content-Type: application/json\r\n'
    printf 'Access-Control-Allow-Origin: *\r\n'
    printf '\r\n'
    if [[ ! -f "$DISCOVER_SCRIPT" ]]; then
        printf '{"error":"syno_discover.py not found"}\n'
        exit 0
    fi
    # Find Python - try python3 first, fall back to python2
    _python=""
    for _py in /bin/python3 /usr/local/bin/python3 /bin/python2 /bin/python; do
        if [[ -x "$_py" ]]; then
            _python="$_py"
            break
        fi
    done
    if [[ -z "$_python" ]]; then
        printf '{"error":"Python not available"}\n'
        exit 0
    fi
    "$_python" "$DISCOVER_SCRIPT" --json --timeout 4
    exit 0
fi

# ---------------------------------------------------------------------------
# action=get_settings
# Returns current settings as JSON.
# ---------------------------------------------------------------------------
if [[ "$_action" == "get_settings" ]]; then
    printf 'Content-Type: application/json\r\n'
    printf '\r\n'

    _discover_nas=$(synogetkeyvalue "$SETTINGS_CONF" discover_nas 2>/dev/null || echo "false")
    _manual_count=$(synogetkeyvalue "$SETTINGS_CONF" manual_nas_count 2>/dev/null || echo "0")
    [[ -z "$_discover_nas" ]] && _discover_nas="false"
    [[ -z "$_manual_count" ]] && _manual_count="0"

    printf '{"discover_nas":%s,"manual_nas":[' "$_discover_nas"
    _first=1
    for (( i=1; i<=_manual_count; i++ )); do
        _entry=$(synogetkeyvalue "$SETTINGS_CONF" "manual_nas${i}" 2>/dev/null)
        [[ -z "$_entry" ]] && continue
        _h=$(echo "$_entry" | cut -d, -f1)
        _ip=$(echo "$_entry" | cut -d, -f2)
        _port=$(echo "$_entry" | cut -d, -f3)
        _en=$(echo "$_entry" | cut -d, -f4)
        [[ "$_en" == "0" ]] && _enabled="false" || _enabled="true"
        [[ $_first -eq 0 ]] && printf ','
        printf '{"hostname":"%s","ip":"%s","port":"%s","enabled":%s}' "$_h" "$_ip" "$_port" "$_enabled"
        _first=0
    done
    printf ']}\n'
    exit 0
fi

# ---------------------------------------------------------------------------
# action=save_settings
# Saves settings from query string to settings.conf.
# Only calls synosetkeyvalue if the value has changed.
# Returns {"ok":true,"changed":true/false}
# Params: discover_nas=true|false
#         manual_nas_count=N
#         manual_nas1=hostname,ip,port  (repeated for each NAS)
# ---------------------------------------------------------------------------
if [[ "$_action" == "save_settings" ]]; then
    printf 'Content-Type: application/json\r\n'
    printf '\r\n'

    # Parse discover_nas
    _discover_nas="false"
    if [[ "${QUERY_STRING:-}" =~ (^|&)discover_nas=([^&]*) ]]; then
        _val="${BASH_REMATCH[2]}"
        [[ "$_val" == "true" ]] && _discover_nas="true"
    fi
    _changed=false

    # Only write discover_nas if value changed
    _cur_discover=$(synogetkeyvalue "$SETTINGS_CONF" discover_nas 2>/dev/null || echo "")
    if [[ "$_cur_discover" != "$_discover_nas" ]]; then
        synosetkeyvalue "$SETTINGS_CONF" discover_nas "$_discover_nas"
        _changed=true
    fi

    # Parse manual_nas_count
    _manual_count=0
    if [[ "${QUERY_STRING:-}" =~ (^|&)manual_nas_count=([^&]*) ]]; then
        _manual_count="${BASH_REMATCH[2]}"
    fi

    # Read old count BEFORE writing new count so the cleanup loop below
    # can remove entries that no longer exist
    _old_count=$(synogetkeyvalue "$SETTINGS_CONF" manual_nas_count 2>/dev/null || echo "0")

    # Only write manual_nas_count if changed
    if [[ "$_old_count" != "$_manual_count" ]]; then
        synosetkeyvalue "$SETTINGS_CONF" manual_nas_count "$_manual_count"
        _changed=true
    fi

    # Parse each manual_nasN entry - only write if changed
    # URL-decode helper: replace %2C -> , and + -> space
    _qs="${QUERY_STRING:-}"
    for (( i=1; i<=_manual_count; i++ )); do
        if [[ "$_qs" =~ (^|&)"manual_nas${i}"=([^&]*) ]]; then
            _entry="${BASH_REMATCH[2]}"
            # URL decode %2C -> comma, + -> space
            _entry="${_entry//%2C/,}"
            _entry="${_entry//%2c/,}"
            _entry="${_entry//+/ }"
            _cur_entry=$(synogetkeyvalue "$SETTINGS_CONF" "manual_nas${i}" 2>/dev/null || echo "")
            if [[ "$_cur_entry" != "$_entry" ]]; then
                synosetkeyvalue "$SETTINGS_CONF" "manual_nas${i}" "$_entry"
                _changed=true
            fi
        fi
    done

    # Remove any old manual_nas entries beyond the new count
    for (( i=_manual_count+1; i<=_old_count; i++ )); do
        _cur_entry=$(synogetkeyvalue "$SETTINGS_CONF" "manual_nas${i}" 2>/dev/null || echo "")
        if [[ -n "$_cur_entry" ]]; then
            synosetkeyvalue "$SETTINGS_CONF" "manual_nas${i}" ""
            _changed=true
        fi
    done

    printf '{"ok":true,"changed":%s}\n' "$_changed"
    exit 0
fi

# ---------------------------------------------------------------------------
# action=get_ha_passive
# Returns passive node drive data from /var/lib/ha/space_disk_info.
# This file is maintained by the Synology HighAvailability package and
# contains a JSON object of all drives on the passive node, keyed by
# slot id (e.g. "0-1", "0-2", ...).
# Only available on HD6500 / SHA cluster (requires HighAvailability pkg).
# ---------------------------------------------------------------------------
if [[ "$_action" == "get_ha_passive" ]]; then
    printf 'Content-Type: application/json\r\n'
    printf '\r\n'

    # Check HA is active
    _runha=$(synogetkeyvalue /etc/synoinfo.conf runha 2>/dev/null || echo "no")
    if [[ "$_runha" != "yes" ]]; then
        printf '{"ha":"none"}\n'
        exit 0
    fi

    _ha_disk_file="/var/lib/ha/space_disk_info"
    if [[ ! -f "$_ha_disk_file" ]] || [[ ! -s "$_ha_disk_file" ]]; then
        printf '{"ha":"unavailable"}\n'
        exit 0
    fi

    # Get passive node hostname for labelling
    _ha_conf="/usr/syno/etc/packages/HighAvailability/ha.conf"
    _passive_ip=$(synogetkeyvalue "$_ha_conf" ip1 2>/dev/null || echo "")
    _local_ip=$(synogetkeyvalue "$_ha_conf" ip0 2>/dev/null || echo "")
    # Determine which is passive by comparing against local interfaces
    _local_ips=$(ip addr show 2>/dev/null | grep -o 'inet [0-9.]*' | awk '{print $2}')
    if echo "$_local_ips" | grep -q "^${_local_ip}$"; then
        _passive_ip=$(synogetkeyvalue "$_ha_conf" ip1 2>/dev/null || echo "")
    else
        _passive_ip=$(synogetkeyvalue "$_ha_conf" ip0 2>/dev/null || echo "")
    fi

    _passive_hostname=$(synogetkeyvalue "$_ha_conf" host1 2>/dev/null || echo "Passive Node")

    _disk_json=$(cat "$_ha_disk_file")
    printf '{"ha":"passive","hostname":"%s","ip":"%s","data":%s}\n' \
        "$_passive_hostname" "$_passive_ip" "$_disk_json"
    exit 0
fi

# ---------------------------------------------------------------------------
# Default action: render main page HTML
# Settings are embedded in the same page and shown/hidden via JS.
# ---------------------------------------------------------------------------
printf 'Content-Type: text/html; charset=utf-8\r\n'
printf 'Access-Control-Allow-Origin: *\r\n'
printf '\r\n'

# Read settings
_discover_nas=$(synogetkeyvalue "$SETTINGS_CONF" discover_nas 2>/dev/null || echo "false")
_manual_count=$(synogetkeyvalue "$SETTINGS_CONF" manual_nas_count 2>/dev/null || echo "0")
[[ -z "$_discover_nas" ]] && _discover_nas="false"
[[ -z "$_manual_count" ]] && _manual_count="0"

# Build manual NAS JSON array for JS
_manual_json="["
_first=1
for (( i=1; i<=_manual_count; i++ )); do
    _entry=$(synogetkeyvalue "$SETTINGS_CONF" "manual_nas${i}" 2>/dev/null)
    [[ -z "$_entry" ]] && continue
    _h=$(echo "$_entry" | cut -d, -f1)
    _ip=$(echo "$_entry" | cut -d, -f2)
    _port=$(echo "$_entry" | cut -d, -f3)
    _en=$(echo "$_entry" | cut -d, -f4)
    # Default enabled=true if field absent (older entries have only 3 fields)
    [[ "$_en" == "0" ]] && _enabled="false" || _enabled="true"
    [[ $_first -eq 0 ]] && _manual_json+=","
    _manual_json+="{\"hostname\":\"${_h}\",\"ip\":\"${_ip}\",\"port\":\"${_port}\",\"enabled\":${_enabled}}"
    _first=0
done
_manual_json+="]"

# Localised strings
_txt_drive_info=$(txt common drive_information "Drive Information")
_txt_loading=$(txt common loading "Loading...")
_txt_settings=$(txt settings settings "Settings")
_txt_discover=$(txt settings discover_local_nas "Discover all local Synology NAS")
_txt_discovering=$(txt settings discovering "Discovering NAS...")
_txt_manual=$(txt settings manual_nas_list "Additional NAS")
_txt_hostname=$(txt settings hostname "Hostname")
_txt_ip=$(txt settings ip_address "IP Address")
#_txt_port=$(txt settings port "Port")
_txt_port=$(txt settings login_port "Login port")
_txt_remove=$(txt settings remove "Remove")
_txt_save=$(txt settings save "Save")
_txt_saved=$(txt settings saved "Saved")
_txt_add=$(txt settings add_device "Add a Device")
_txt_back=$(txt settings back "Back")
_txt_cancel=$(txt settings cancel "Cancel")
_txt_slot=$(txt common drive_id "Drive ID")
_txt_model=$(txt common model "Model")
_txt_serial=$(txt common serial_number "Serial Number")
_txt_status=$(txt common status "Status")

cat << STYLE
<style>
body { font-family: Verdana, Arial, sans-serif; font-size: 13px; color: #333;
       margin: 16px; margin-right: 14px; background: transparent; overflow-y: auto; }
h2   { margin-top: 0; font-size: 15px; color: #333; }
pre  { background: #f4f4f4; border: 1px solid #ddd; border-radius: 4px;
       padding: 12px; font-size: 12px; line-height: 1.6;
       white-space: pre-wrap; word-break: break-all;
       box-sizing: border-box; max-width: 100%; }
table { border-collapse: collapse; width: 100%;
        box-sizing: border-box; table-layout: auto;
        font-family: Verdana, Arial, sans-serif; font-size: 13px; }
col.id       { width: 11%; min-width: 65px; }
col.num      { width: 15%; min-width: 75px; }
col.location { width: 13%; min-width: 50px; }
col.model    { width: 26%; min-width: 140px; }
col.serial   { width: 20%; min-width: 75px; }
col.status   { width: auto; min-width: 110px; }
th.id, td.id             { white-space: nowrap; }
th.num, td.num           { white-space: nowrap; }
th.location, td.location { white-space: nowrap; }
th.model, td.model       { white-space: nowrap; }
th.serial, td.serial     { white-space: nowrap; }
th.status, td.status     { white-space: nowrap; }
th { text-align: left; padding: 5px 14px 5px 5px;
     border-bottom: 2px solid #ccc; color: #555;
     font-family: Verdana, Arial, sans-serif; font-size: 13px; }
td { padding: 5px 14px 5px 5px; border-bottom: 1px solid #eee; }
td.num    { color: #057FEB; }
td.serial { color: #b5800a; }
td.status-healthy  { color: #1CA600; }
td.status-warning  { color: #FF7F00; }
td.status-critical { color: #E64040; }
td.status-failing  { color: #E64040; }
.err { color: #c00; }
a    { color: #0073c0; }
/* Top bar - shared by both views */
.topbar { display: flex; justify-content: flex-end; margin-bottom: 4px; padding-right: 8px; }
.icon-btn { background: #e8eef3; border: 1px solid #e8eef3; border-radius: 4px;
            cursor: pointer; padding: 4px 10px; line-height: 0; }
.icon-btn:hover { background: #e8eef3; border-color: #aaa; }
.icon-btn:disabled { cursor: default; border-color: #e8eef3; }
.icon-btn:disabled:hover { border-color: #e8eef3; }
.icon-btn:disabled img { content: url('/webman/3rdparty/drive_info/images/bt_gear_disabled.png'); }
/* Remote NAS sections */
.remote-section { margin-top: 20px; }
.remote-section h2 { color: #333; }
.remote-err { color: #999; font-size: 12px; font-style: italic; }
/* Settings panel */
.section { margin-bottom: 20px; }
.section-title { font-size: 13px; font-weight: bold; color: #555;
                 margin-bottom: 8px; border-bottom: 1px solid #eee;
                 padding-bottom: 4px; padding-left: 10px; }
.toggle-row { display: flex; align-items: center; gap: 10px; padding: 6px 0; }
#discover-row { padding-left: 8px; }
.toggle { position: relative; display: inline-block; width: 40px; height: 22px; }
.toggle input { opacity: 0; width: 0; height: 0; }
.toggle-slider { position: absolute; cursor: pointer; top: 0; left: 0;
                 right: 0; bottom: 0; background: #ccc; border-radius: 22px;
                 transition: 0.2s; }
.toggle-slider:before { position: absolute; content: ""; height: 16px; width: 16px;
                         left: 3px; bottom: 3px; background: white;
                         border-radius: 50%; transition: 0.2s; }
input:checked + .toggle-slider { background: #2196F3; }
input:checked + .toggle-slider:before { transform: translateX(18px); }
#settings-panel table { font-size: 13px; }
#settings-panel th { padding: 5px 8px; }
#settings-panel td { padding: 4px 8px; vertical-align: middle; }
#settings-panel td input { font-size: 12px; padding: 3px 5px; border: 1px solid #ccc;
                            border-radius: 3px; width: 100%; box-sizing: border-box; }
#settings-panel td.port-cell input { width: 70px; }
#settings-panel th:last-child,
#settings-panel td:last-child { width: 1%; white-space: nowrap; padding-left: 4px; }
#settings-panel th:first-child,
#settings-panel td:first-child { width: 1%; white-space: nowrap; padding-right: 4px; }
tr.nas-row-disabled td input { color: #bbb; }
tr.nas-row-disabled td.port-cell input { color: #bbb; }
.btn-remove { background: none; border: 1px solid #ccc; border-radius: 4px;
              cursor: pointer; color: #c00; font-size: 13px; padding: 3px 10px; }
.btn-remove:hover { background: #fde0e0; border-color: #c00; }
.btn-add { background: none; border: 1px solid #ccc; border-radius: 4px;
           cursor: pointer; color: #0073c0; font-size: 13px; padding: 3px 10px;
           margin-top: 8px; margin-left: 8px; }
.btn-add:hover { background: #c8ebfa; border-color: #0073c0; }
.btn-save { background: #0073c0; border: none; border-radius: 4px;
            cursor: pointer; color: white; font-size: 13px;
            padding: 5px 18px; }
.btn-save:hover { background: #005fa3; }
.btn-cancel { background: white; border: 1px solid #ccc; border-radius: 4px;
              cursor: pointer; color: #333; font-size: 13px;
              padding: 5px 18px; }
.btn-cancel:hover { background: #f0f0f0; border-color: #aaa; }
.settings-footer { display: flex; justify-content: flex-end; gap: 10px;
                   margin-top: 16px; padding-top: 12px;
                   border-top: 1px solid #eee; padding-right: 8px; }
.save-feedback { display: inline-block; margin-right: auto; color: #1CA600;
                 font-size: 12px; opacity: 0; transition: opacity 0.3s;
                 align-self: center; }
</style>
STYLE

# ---------------------------------------------------------------------------
# Top bar - single button that toggles between gear and home
# ---------------------------------------------------------------------------
cat << TOPBAR
<div class="topbar">
  <button class="icon-btn" id="nav-btn"
          onclick="showSettings()"
          title="${_txt_settings}" disabled><img src="/webman/3rdparty/drive_info/images/bt_gear.png" width="20" height="20" alt=""></button>
</div>
TOPBAR

# ---------------------------------------------------------------------------
# Main view
# ---------------------------------------------------------------------------
cat << MAINVIEW
<div id="main-view">
MAINVIEW

# Check script exists
if [[ ! -f "$SCRIPT" ]]; then
    echo "<p class=\"err\">$(txt errors err_script_missing "drive_info.sh not found. Try reinstalling the package.")</p>"
    echo "</div>"
    exit 0
fi

# Check sudo permission
if ! sudo -n -l "$SCRIPT" >/dev/null 2>&1; then
    cat << NOPERMS
<h2 style="color:#c00;">$(txt errors err_noperms_title "Permissions not configured")</h2>
<p>$(txt errors err_noperms_desc "This package needs elevated permissions to read drive information.")</p>
<p>$(txt errors err_noperms_ssh "Connect to your NAS via SSH and run:")</p>
<pre>sudo -i
echo "drive_info ALL=(root) NOPASSWD: $SCRIPT" \\
    &gt; $SUDOERS_FILE
chmod 0440 $SUDOERS_FILE</pre>
<p>$(txt errors err_noperms_reopen "Then close and reopen this window.")</p>
<p>$(txt errors err_see_details "See <a href=\"https://github.com/007revad/Synology_drive_info/blob/main/set_package_permissions.md\" target=\"_blank\">set_package_permissions.md</a> for full details.")</p>
</div>
<script>document.getElementById("nav-btn").disabled=false;</script>
NOPERMS
    exit 0
fi

# Spinner
cat << SPINNER
<div id="loading" style="margin-bottom:8px;">
  <img src="/webman/3rdparty/drive_info/images/wait_triangle_blue_40p.gif" alt="" width="30" height="30" style="vertical-align:middle;margin-right:6px;">
  <span>${_txt_loading}</span>
</div>
<div id="drive-table"></div>
<script>
function showResult(html) {
    document.getElementById('loading').style.display = 'none';
    document.getElementById('drive-table').innerHTML = html;
    var btn = document.getElementById('nav-btn');
    btn.disabled = false;
}
</script>
SPINNER

# Flush spinner to browser before running the slow script
dd if=/dev/zero bs=4096 count=1 2>/dev/null | tr '\0' ' '

# Run drive_info.sh as root via sudo
STDERR_TMP=$(mktemp)
OUTPUT=$(sudo "${SCRIPT}" 2>"$STDERR_TMP")
EXIT_CODE=$?
STDERR_OUT=$(cat "$STDERR_TMP")
rm -f "$STDERR_TMP"

# Clear spinner and enable settings button
echo '<script>document.getElementById("loading").style.display="none";document.getElementById("nav-btn").disabled=false;</script>'

# Check if sudo failed
if echo "$STDERR_OUT" | grep -qi "not in the sudoers\|sudoers file\|not allowed\|password is required"; then
    cat << SUDOFAIL
<h2 style="color:#c00;">$(txt errors err_sudofail_title "Permissions not configured correctly")</h2>
<p>$(txt errors err_sudofail_desc "The sudoers entry exists but sudo failed. Check the entry is correct:")</p>
<pre>cat $SUDOERS_FILE</pre>
<p>$(txt errors err_sudofail_must_contain "It should contain exactly:")</p>
<pre>drive_info ALL=(root) NOPASSWD: $SCRIPT</pre>
<p>$(txt errors err_see_details "See <a href=\"https://github.com/007revad/Synology_drive_info/blob/main/set_package_permissions.md\" target=\"_blank\">set_package_permissions.md</a> for full details.")</p>
</div>
SUDOFAIL
    exit 0
fi

if [[ $EXIT_CODE -ne 0 ]]; then
    echo "<p class=\"err\">drive_info.sh exited with code $EXIT_CODE.</p>"
    [[ -n "$STDERR_OUT" ]] && echo "<pre>$(echo "$STDERR_OUT" | sed 's/</\&lt;/g;s/>/\&gt;/g')</pre>"
    echo "</div>"
    exit 0
fi

# Parse drive_info.sh plain-text output into HTML tables
#echo "<h2>${_txt_drive_info}</h2>"  # Drive Information heading
# Get local NAS identity for the heading
_local_hostname=$(cat /proc/sys/kernel/hostname 2>/dev/null || hostname)
_local_model=$(synogetkeyvalue /etc.defaults/synoinfo.conf upnpmodelname 2>/dev/null)
if [[ -z "$_local_model" && -f /proc/sys/kernel/syno_hw_version ]]; then
    _local_model=$(cat /proc/sys/kernel/syno_hw_version 2>/dev/null || echo "")
    if [[ ${_local_model,,} =~ 'pv10-j'$ ]]; then
        _local_model=${_local_model%??????}+
    elif [[ ${_local_model} =~ '-j'$ ]]; then
        _local_model=${_local_model%??}
    fi
fi
[[ -z "$_local_model" ]] && _local_model=""

# Get local IP - prefer the default-route interface address
_local_ip=$(ip route get 1.1.1.1 2>/dev/null | grep -o 'src [0-9.]*' | awk '{print $2}')
[[ -z "$_local_ip" ]] && _local_ip=$(hostname -i 2>/dev/null | awk '{print $1}')

_local_subtitle=""
if [[ -n "$_local_ip" || -n "$_local_model" ]]; then
    _local_subtitle=" <span style=\"font-weight:normal;font-size:13px;color:#999;\"> &nbsp; ${_local_ip} &nbsp; ${_local_model}</span>"
fi
echo "<h2>${_local_hostname}${_local_subtitle}</h2>"

in_table=0
headers=()
col_count=0

# Pre-scan to check if any Location column values are non-empty
HAS_LOCATION=0
scan_in_table=0
scan_headers=()
scan_col_starts=()
scan_col_count=0
while IFS= read -r line; do
    trimmed="${line#"${line%%[![:space:]]*}"}"
    if [[ "$trimmed" =~ ^-+$ ]]; then
        scan_in_table=1; continue
    fi

    if [[ $scan_in_table -eq 1 ]] && [[ ${#scan_headers[@]} -eq 0 ]] && [[ -n "$trimmed" ]]; then
        IFS=$'\n' read -r -d '' -a scan_headers <<< "$(echo "$trimmed" | grep -oP '\S.*?(?=  |\s*$)')" || true
        scan_col_count=${#scan_headers[@]}
        scan_col_starts=()
        pos=0
        for h in "${scan_headers[@]}"; do
            rest="${line:$pos}"
            prefix="${rest%%"$h"*}"
            scan_col_starts+=("$(( pos + ${#prefix} ))")
            pos=$(( pos + ${#prefix} + ${#h} ))
        done
        continue
    fi

    if [[ $scan_in_table -eq 1 ]] && [[ ${#scan_headers[@]} -gt 0 ]] && [[ -n "$trimmed" ]] && (( scan_col_count > 2 )); then
        start="${scan_col_starts[2]}"
        if (( 3 < scan_col_count )); then
            len=$(( scan_col_starts[3] - start - 2 ))
        else
            len=$(( ${#line} - start ))
        fi
        val="${line:$start:$len}"
        val="${val%"${val##*[![:space:]]}"}"
        if [[ -n "$val" ]]; then HAS_LOCATION=1; break; fi
        continue
    fi

    if [[ $scan_in_table -eq 1 ]] && [[ ${#scan_headers[@]} -gt 0 ]] && [[ -z "$trimmed" ]]; then
        scan_in_table=0; scan_headers=(); continue
    fi
done <<< "$OUTPUT"

while IFS= read -r line; do
    trimmed="${line#"${line%%[![:space:]]*}"}"

    # Separator line
    if [[ "$trimmed" =~ ^-+$ ]]; then
        if [[ $in_table -eq 0 ]]; then
            in_table=1
            if [[ $HAS_LOCATION -eq 1 ]]; then
                echo '<table><colgroup><col class="id"><col class="num"><col class="location"><col class="model"><col class="serial"><col class="status"></colgroup>'
            else
                echo '<table><colgroup><col class="id"><col class="num"><col class="model"><col class="serial"><col class="status"></colgroup>'
            fi
        fi
        continue
    fi

    if [[ $in_table -eq 1 ]] && [[ ${#headers[@]} -eq 0 ]] && [[ -n "$trimmed" ]]; then
        # Header row — split on 2+ spaces
        IFS=$'\n' read -r -d '' -a headers <<< "$(echo "$trimmed" | grep -oP '\S.*?(?=  |\s*$)')" || true
        col_count=${#headers[@]}

        # Record each header's start position so data rows (which can have
        # blank cells, e.g. an empty Location) can be sliced by position
        # instead of by matching non-whitespace runs.
        col_starts=()
        pos=0
        for h in "${headers[@]}"; do
            rest="${line:$pos}"
            prefix="${rest%%"$h"*}"
            col_starts+=("$(( pos + ${#prefix} ))")
            pos=$(( pos + ${#prefix} + ${#h} ))
        done

        echo "<thead><tr>"
        col_classes=("id" "num" "location" "model" "serial" "status")
        for idx in "${!headers[@]}"; do
            cls="${col_classes[$idx]:-}"
            [[ "$cls" == "location" && $HAS_LOCATION -eq 0 ]] && continue
            echo "<th class=\"$cls\">$(echo "${headers[$idx]}" | sed 's/</\&lt;/g;s/>/\&gt;/g')</th>"
        done
        echo "</tr></thead><tbody>"
        continue
    fi

    if [[ $in_table -eq 1 ]] && [[ ${#headers[@]} -gt 0 ]] && [[ -n "$trimmed" ]]; then
        # Data row — slice by the column positions recorded from the header,
        # since a whitespace-based split can't represent a blank cell.
        echo "<tr>"
        for (( c=0; c<col_count; c++ )); do
            start="${col_starts[$c]}"
            if (( c + 1 < col_count )); then
                len=$(( col_starts[c+1] - start - 2 ))  # -2 for the column gap
            else
                len=$(( ${#line} - start ))
            fi
            val="${line:$start:$len}"
            val="${val%"${val##*[![:space:]]}"}"  # trim trailing padding
            val="$(echo "$val" | sed 's/</\&lt;/g;s/>/\&gt;/g')"
            if [[ $c -eq 0 ]]; then
                echo "<td class=\"id\">$val</td>"
            elif [[ $c -eq 1 ]]; then
                echo "<td class=\"num\">$val</td>"
            elif [[ $c -eq 2 ]]; then
                [[ $HAS_LOCATION -eq 0 ]] && continue
                echo "<td class=\"location\">$val</td>"
            elif [[ $c -eq 3 ]]; then
                echo "<td class=\"model\">$val</td>"
            elif [[ $c -eq 4 ]]; then
                echo "<td class=\"serial\">$val</td>"
            elif [[ $c -eq 5 ]]; then
                case "$val" in
                    healthy::*)  css_class="status-healthy";  val="${val#healthy::}"  ;;
                    warning::*)  css_class="status-warning";  val="${val#warning::}"  ;;
                    critical::*) css_class="status-critical"; val="${val#critical::}" ;;
                    failing::*)  css_class="status-failing";  val="${val#failing::}"  ;;
                    *)           css_class="status"                                   ;;
                esac
                echo "<td class=\"$css_class\">$val</td>"
            else
                echo "<td>$val</td>"
            fi
        done
        echo "</tr>"
        continue
    fi

    if [[ $in_table -eq 1 ]] && [[ ${#headers[@]} -gt 0 ]] && [[ -z "$trimmed" ]]; then
        # Blank line ends table section
        echo "</tbody></table><br>"
        in_table=0; headers=(); continue
    fi
done <<< "$OUTPUT"

[[ $in_table -eq 1 ]] && echo "</tbody></table>"

# Remote NAS container - populated by JS after page load
echo '<div id="remote-nas-container"></div>'

# HA passive node container - populated by JS after page load
echo '<div id="ha-passive-container"></div>'

# Close main-view div
echo '</div>'

# ---------------------------------------------------------------------------
# Settings panel - hidden until gear button clicked
# ---------------------------------------------------------------------------
cat << SETTINGSHTML
<div id="settings-panel" style="display:none;">
  <h2>&nbsp;&nbsp;${_txt_settings}</h2>

  <div class="section">
    <div class="toggle-row" id="discover-row">
      <label class="toggle">
        <input type="checkbox" id="discover_nas" $([ "$_discover_nas" = "true" ] && echo "checked")>
        <span class="toggle-slider"></span>
      </label>
      <span>${_txt_discover}</span>
    </div>
  </div>

  <div class="section">
    <div class="section-title">${_txt_manual}</div>
    <table id="nas-table">
      <thead><tr>
        <th></th>
        <th>${_txt_hostname}</th>
        <th>${_txt_ip}</th>
        <th>${_txt_port}</th>
        <th></th>
      </tr></thead>
      <tbody id="nas-tbody"></tbody>
    </table>
    <button class="btn-add" onclick="addRow()">${_txt_add}</button>
  </div>

  <div class="settings-footer">
    <span class="save-feedback" id="save-feedback">${_txt_saved} ✓</span>
    <button class="btn-cancel" onclick="cancelSettings()">${_txt_cancel}</button>
    <button class="btn-save" onclick="saveSettings()">${_txt_save}</button>
  </div>
</div>
SETTINGSHTML

# ---------------------------------------------------------------------------
# JavaScript - settings panel + remote NAS fetching
# ---------------------------------------------------------------------------
cat << JAVASCRIPT
<script>
var nasData = ${_manual_json};
var nasDataSaved = JSON.parse(JSON.stringify(nasData));  // snapshot for Cancel
var txtRemove = "${_txt_remove}";
var dirty = false;  // true only after settings have been saved

// ---------------------------------------------------------------------------
// Settings panel show/hide
// ---------------------------------------------------------------------------
function showSettings() {
    document.getElementById('main-view').style.display = 'none';
    document.getElementById('settings-panel').style.display = '';
    var btn = document.getElementById('nav-btn');
    btn.innerHTML = '<img src="/webman/3rdparty/drive_info/images/bt_home.png" width="20" height="20" alt="">';
    btn.title = '${_txt_back}';
    btn.onclick = cancelSettings;
    renderTable();
}

function cancelSettings() {
    // Discard any unsaved changes by re-reading from the last-saved nasData snapshot
    nasData = JSON.parse(JSON.stringify(nasDataSaved));
    document.getElementById('settings-panel').style.display = 'none';
    document.getElementById('main-view').style.display = '';
    var btn = document.getElementById('nav-btn');
    btn.innerHTML = '<img src="/webman/3rdparty/drive_info/images/bt_gear.png" width="20" height="20" alt="">';
    btn.title = '${_txt_settings}';
    btn.onclick = showSettings;
}

function goBack() {
    if (dirty) {
        // Settings were saved - reload page to apply changes
        window.location.href = 'api.cgi?_ts=' + new Date().getTime();
    } else {
        cancelSettings();
    }
}

// ---------------------------------------------------------------------------
// Settings table
// ---------------------------------------------------------------------------
function renderTable() {
    var tbody = document.getElementById('nas-tbody');
    tbody.innerHTML = '';
    for (var i = 0; i < nasData.length; i++) {
        tbody.appendChild(makeRow(i, nasData[i]));
    }
}

function makeRow(idx, entry) {
    var enabled = entry.enabled !== false;
    var tr = document.createElement('tr');
    tr.className = enabled ? '' : 'nas-row-disabled';
    tr.innerHTML =
        '<td><label class="toggle"><input type="checkbox" ' + (enabled ? 'checked' : '') +
            ' onchange="toggleRow(' + idx + ',this.checked)"><span class="toggle-slider"></span></label></td>' +
        '<td><input type="text" value="' + esc(entry.hostname) + '" onchange="nasData[' + idx + '].hostname=this.value;"></td>' +
        '<td><input type="text" value="' + esc(entry.ip) + '" onchange="nasData[' + idx + '].ip=this.value;"></td>' +
        '<td class="port-cell"><input type="text" value="' + esc(entry.port) + '" onchange="nasData[' + idx + '].port=this.value;"></td>' +
        '<td><button class="btn-remove" onclick="removeRow(' + idx + ')">' + txtRemove + '</button></td>';
    return tr;
}

function toggleRow(idx, checked) {
    nasData[idx].enabled = checked;
    // Update row dimming without full re-render (avoids losing focus)
    var rows = document.getElementById('nas-tbody').rows;
    if (rows[idx]) rows[idx].className = checked ? '' : 'nas-row-disabled';
}

function addRow() {
    nasData.push({hostname: '', ip: '', port: '5000', enabled: true});
    renderTable();
    var rows = document.getElementById('nas-tbody').rows;
    if (rows.length > 0) {
        rows[rows.length - 1].cells[1].querySelector('input').focus();
    }
}

function removeRow(idx) {
    nasData.splice(idx, 1);
    renderTable();
}

function esc(s) {
    return (s || '').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;');
}

function saveSettings() {
    var valid = [];
    for (var i = 0; i < nasData.length; i++) {
        var h = nasData[i].hostname.trim();
        var ip = nasData[i].ip.trim();
        var port = nasData[i].port.trim() || '5000';
        var enabled = nasData[i].enabled !== false;  // default true
        if (h === '' && ip === '') continue;
        valid.push(h + ',' + ip + ',' + port + ',' + (enabled ? '1' : '0'));
    }

    var discover = document.getElementById('discover_nas').checked ? 'true' : 'false';
    var qs = 'action=save_settings&discover_nas=' + discover +
             '&manual_nas_count=' + valid.length;
    for (var j = 0; j < valid.length; j++) {
        qs += '&manual_nas' + (j + 1) + '=' + encodeURIComponent(valid[j]);
    }

    var xhr = new XMLHttpRequest();
    xhr.open('GET', 'api.cgi?' + qs, true);
    xhr.onreadystatechange = function() {
        if (xhr.readyState === 4) {
            // Always reload after Save so changes take effect immediately
            window.location.href = 'api.cgi?_ts=' + new Date().getTime();
        }
    };
    xhr.send();
}

// ---------------------------------------------------------------------------
// HA Passive node fetching
// Reads /var/lib/ha/space_disk_info via api.cgi?action=get_ha_passive.
// Only present on HD6500 / SHA clusters running the HighAvailability package.
// ---------------------------------------------------------------------------
function fetchHAPassive() {
    var container = document.getElementById('ha-passive-container');
    var xhr = new XMLHttpRequest();
    xhr.open('GET', 'api.cgi?action=get_ha_passive', true);
    xhr.timeout = 10000;
    xhr.onreadystatechange = function() {
        if (xhr.readyState !== 4) return;
        if (xhr.status !== 200) return;
        var resp;
        try { resp = JSON.parse(xhr.responseText); } catch(e) { return; }
        if (!resp || resp.ha !== 'passive' || !resp.data) return;

        var label = resp.hostname || 'Passive Node';
        var ip    = resp.ip || '';

        var section = document.createElement('div');
        section.className = 'remote-section';
        section.innerHTML =
            '<h2>' + escHtml(label) +
            (ip ? ' <span style="font-weight:normal;font-size:11px;color:#999;">(' + escHtml(ip) + ' \u2014 Passive)</span>' : ' <span style="font-weight:normal;font-size:11px;color:#999;">(Passive)</span>') +
            '</h2>' +
            buildHAPassiveTable(resp.data);
        container.appendChild(section);
    };
    xhr.send();
}

function buildHAPassiveTable(drives) {
    // drives is an object keyed by slot id e.g. {"0-1":{...},"0-2":{...}}
    // Sort by slot_id numerically
    var keys = Object.keys(drives).sort(function(a, b) {
        var na = parseInt(a.split('-')[1], 10);
        var nb = parseInt(b.split('-')[1], 10);
        return na - nb;
    });

    if (keys.length === 0) return '<p class="remote-err">No drive data available.</p>';

    var html = '<table><colgroup>' +
        '<col class="num"><col class="model"><col class="serial"><col class="status">' +
        '</colgroup><thead><tr>' +
        '<th class="num">${_txt_slot}</th>' +
        '<th class="model">${_txt_model}</th>' +
        '<th class="serial">${_txt_serial}</th>' +
        '<th class="status">${_txt_status}</th>' +
        '</tr></thead><tbody>';

    for (var i = 0; i < keys.length; i++) {
        var d = drives[keys[i]];
        var slotNum  = d.slot_id !== undefined ? d.slot_id : keys[i].split('-')[1];
        var model    = d.model   || '';
        var serial   = d.ui_serial || d.serial || '';
        var statusKey = d.drive_status_key || d.status || '';
        var temp     = (d.temp !== undefined && d.temp !== null) ? d.temp + '\u00b0C' : '';

        var statusClass, statusText;
        switch (statusKey) {
            case 'normal':
                statusClass = 'status-healthy';
                statusText  = temp ? 'Normal ' + temp : 'Normal';
                break;
            case 'warning':
                statusClass = 'status-warning';
                statusText  = temp ? 'Warning ' + temp : 'Warning';
                break;
            case 'critical':
            case 'error':
                statusClass = 'status-critical';
                statusText  = temp ? 'Critical ' + temp : 'Critical';
                break;
            case 'failing':
                statusClass = 'status-failing';
                statusText  = 'Failing';
                break;
            default:
                statusClass = 'status';
                statusText  = statusKey || (temp || '-');
        }

        html +=
            '<tr>' +
            '<td class="num">' + escHtml(String(slotNum)) + '</td>' +
            '<td class="model">' + escHtml(model) + '</td>' +
            '<td class="serial">' + escHtml(serial) + '</td>' +
            '<td class="' + statusClass + '">' + escHtml(statusText) + '</td>' +
            '</tr>';
    }

    html += '</tbody></table>';
    return html;
}

// ---------------------------------------------------------------------------
// Remote NAS fetching
// ---------------------------------------------------------------------------
function fetchRemoteNAS() {
    var container = document.getElementById('remote-nas-container');

    // Always fetch manual NAS entries from settings
    var xhr = new XMLHttpRequest();
    xhr.open('GET', 'api.cgi?action=get_settings', true);
    xhr.onreadystatechange = function() {
        if (xhr.readyState !== 4) return;
        var settings = {};
        try { settings = JSON.parse(xhr.responseText); } catch(e) { return; }

        // If discovery enabled, run it first then merge manual
        if (settings.discover_nas === true || settings.discover_nas === 'true') {
            var spinner = document.createElement('div');
            spinner.id = 'discover-spinner';
            spinner.style.cssText = 'margin-top:20px; font-size:12px;';
            spinner.innerHTML = '<img src="/webman/3rdparty/drive_info/images/wait_triangle_blue_40p.gif" width="30" height="30" style="vertical-align:middle;margin-right:6px;">${_txt_discovering}';
            container.appendChild(spinner);

            var dxhr = new XMLHttpRequest();
            dxhr.open('GET', 'api.cgi?action=discover', true);
            dxhr.onreadystatechange = function() {
                if (dxhr.readyState !== 4) return;
                var sp = document.getElementById('discover-spinner');
                if (sp) sp.parentNode.removeChild(sp);
                var discovered = [];
                try { discovered = JSON.parse(dxhr.responseText); } catch(e) {}
                if (!Array.isArray(discovered)) discovered = [];
                // Merge manual NAS not already in discovered list
                var manual = settings.manual_nas || [];
                var ips = {};
                discovered.forEach(function(n) { ips[n.ip] = true; });
                manual.forEach(function(m) {
                    if (m.ip && !ips[m.ip]) discovered.push(m);
                });
                fetchAllRemote(discovered);
            };
            dxhr.send();
        } else {
            // Discovery off - just use manual NAS
            fetchAllRemote(settings.manual_nas || []);
        }
    };
    xhr.send();
}

function fetchAllRemote(nasList) {
    nasList.forEach(function(nas) {
        if (nas.enabled === false) return;  // skip disabled entries
        fetchOneDriveInfo(nas);
    });
}

function fetchOneDriveInfo(nas) {
    var ip = nas.ip;
    var port = nas.port || nas.http_port || 5000;
    var hostname = nas.hostname || ip;
    var url = 'http://' + ip + ':' + port + '/webman/3rdparty/drive_info/api.cgi';
    var container = document.getElementById('remote-nas-container');

    // Create section div immediately so order is preserved
    var section = document.createElement('div');
    section.className = 'remote-section';
    section.id = 'remote-' + ip.replace(/\./g, '-');
    section.innerHTML = '<h2>' + escHtml(hostname) +
        ' <span style="font-weight:normal;font-size:13px;color:#999;">(' + escHtml(ip) + ')</span></h2>' +
        '<div class="nas-spinner"><img src="/webman/3rdparty/drive_info/images/wait_triangle_blue_40p.gif" width="30" height="30" style="vertical-align:middle;margin-right:6px;"><span style="font-size:12px;">${_txt_loading}</span></div>';
    container.appendChild(section);

    // Get accurate hostname/model from action=info first
    var ixhr = new XMLHttpRequest();
    ixhr.open('GET', url + '?action=info', true);
    ixhr.timeout = 5000;
    ixhr.onreadystatechange = function() {
        if (ixhr.readyState !== 4) return;
        if (ixhr.status === 200) {
            try {
                var info = JSON.parse(ixhr.responseText);
                if (info.hostname) {
                    section.querySelector('h2').innerHTML =
                        escHtml(info.hostname) +
                        ' <span style="font-weight:normal;font-size:13px;color:#999;"> &nbsp; ' +
                        escHtml(ip) + ' &nbsp; ' + escHtml(info.model) + '</span>';
                }
            } catch(e) {}
        }
        fetchDriveTable(section, url);
    };
    ixhr.onerror = function() { fetchDriveTable(section, url); };
    ixhr.send();
}

function fetchDriveTable(section, url) {
    var fxhr = new XMLHttpRequest();
    fxhr.open('GET', url, true);
    fxhr.timeout = 15000;
    fxhr.onreadystatechange = function() {
        if (fxhr.readyState !== 4) return;
        var sp = section.querySelector('.nas-spinner');
        if (sp) sp.parentNode.removeChild(sp);
        if (fxhr.status === 200) {
            var html = fxhr.responseText;
            html = html.replace(/<style[\s\S]*?<\/style>/gi, '');
            html = html.replace(/<script[\s\S]*?<\/script>/gi, '');
            html = html.replace(/<div id="loading"[^>]*>[\s\S]*?<\/div>/gi, '');
            html = html.replace(/<div id="drive-table"[^>]*><\/div>/gi, '');
            html = html.replace(/<div id="remote-nas-container"[^>]*><\/div>/gi, '');
            html = html.replace(/<div id="settings-panel"[\s\S]*<\/div>/gi, '');
            html = html.replace(/<div class="topbar"[\s\S]*?<\/div>/gi, '');
            html = html.replace(/<div id="main-view"[^>]*>/gi, '');
            html = html.replace(/<h2>[\s\S]*?<\/h2>/gi, '');
            section.innerHTML += html;
        } else {
            section.innerHTML += '<p class="remote-err">HTTP ' + fxhr.status + '</p>';
        }
    };
    fxhr.onerror = function() {
        var sp = section.querySelector('.nas-spinner');
        if (sp) sp.parentNode.removeChild(sp);
        section.innerHTML += '<p class="remote-err">drive_info not installed or not reachable</p>';
    };
    fxhr.send();
}

function escHtml(s) {
    return (s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

fetchHAPassive();
fetchRemoteNAS();
</script>
JAVASCRIPT
