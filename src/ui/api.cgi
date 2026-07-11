#!/bin/bash

PKG_NAME="drive_info"
PKG_ROOT="/var/packages/${PKG_NAME}"
TARGET_DIR="${PKG_ROOT}/target"
SCRIPT="${TARGET_DIR}/ui/bin/drive_info.sh"
SMART_SCRIPT="${TARGET_DIR}/ui/bin/smart_info.sh"
SUDOERS_FILE="/etc/sudoers.d/${PKG_NAME}"

# Get DSM major version
dsm=$(/usr/syno/bin/synogetkeyvalue /etc.defaults/VERSION majorversion)

#---------------------------------------------------------------------------
# Settings file location
# DSM 7: var/ exists and is writable by drive_info (run-as: package)
# DSM 6: var/ doesn't exist; use etc/ (chmod 666 set in postinst)
#---------------------------------------------------------------------------
if [[ -d "${PKG_ROOT}/var" ]]; then
    SETTINGS_CONF="${PKG_ROOT}/var/settings.conf"
else
    SETTINGS_CONF="${PKG_ROOT}/etc/settings.conf"
fi

#---------------------------------------------------------------------------
# JSON API actions - handled before any HTML output
#---------------------------------------------------------------------------

# Parse action from QUERY_STRING
_action=""
if [[ "${QUERY_STRING:-}" =~ (^|&)action=([^&]*) ]]; then
    _action="${BASH_REMATCH[2]}"
fi


#---------------------------------------------------------------------------
# Language argument handling
#---------------------------------------------------------------------------
_lang=""
if [[ "${QUERY_STRING:-}" =~ (^|&)lang=([^&]*) ]]; then
    _lang="${BASH_REMATCH[2]}"
    # Validate it's a real lang code
    if [[ ! "$_lang" =~ ^(chs|cht|csy|dan|enu|fre|ger|hun|ita|jpn|krn|nld|nor|plk|ptb|ptg|rus|spn|sve|tha|trk)$ ]]; then
        _lang=""
    fi
fi
# Fall back to local setting if not supplied
[[ -z "$_lang" ]] && _lang="$(get_key_value /etc/synoinfo.conf maillang 2>/dev/null)"

source "${TARGET_DIR}/ui/modules/get_text.sh" "$_lang"

#---------------------------------------------------------------------------
# action=info
# Returns JSON identifying this NAS. No sudo needed.
# Used by remote NAS fetch so the frontend knows who responded.
#---------------------------------------------------------------------------
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

#---------------------------------------------------------------------------
# action=discover
# Runs syno_discover.py and streams the JSON NAS list.
# Returns the other NAS on the LAN (the local NAS is not included in the
# findhostd responses - the frontend adds it separately via action=info).
#---------------------------------------------------------------------------
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

#---------------------------------------------------------------------------
# action=get_settings
# Returns current settings as JSON.
#---------------------------------------------------------------------------
if [[ "$_action" == "get_settings" ]]; then
    printf 'Content-Type: application/json\r\n'
    printf '\r\n'

    _discover_nas=$(synogetkeyvalue "$SETTINGS_CONF" discover_nas 2>/dev/null || echo "false")
    _show_volume_info=$(synogetkeyvalue "$SETTINGS_CONF" show_volume_info 2>/dev/null || echo "false")
    _show_smart_important=$(synogetkeyvalue "$SETTINGS_CONF" show_smart_important 2>/dev/null || echo "false")
    _smart_schedule_enable=$(synogetkeyvalue "$SETTINGS_CONF" smart_schedule_enable 2>/dev/null || echo "false")
    _smart_notify_email=$(synogetkeyvalue "$SETTINGS_CONF" smart_notify_email 2>/dev/null || echo "")
    _smart_notify_error_only=$(synogetkeyvalue "$SETTINGS_CONF" smart_notify_error_only 2>/dev/null || echo "false")
    _manual_count=$(synogetkeyvalue "$SETTINGS_CONF" manual_nas_count 2>/dev/null || echo "0")
    [[ -z "$_discover_nas" ]] && _discover_nas="false"
    [[ -z "$_show_volume_info" ]] && _show_volume_info="false"
    [[ -z "$_show_smart_important" ]] && _show_smart_important="false"
    [[ -z "$_smart_schedule_enable" ]] && _smart_schedule_enable="false"
    [[ -z "$_smart_notify_error_only" ]] && _smart_notify_error_only="false"
    [[ -z "$_manual_count" ]] && _manual_count="0"

    # Escape email for safe JSON string embedding (backslash and double-quote)
    _smart_notify_email_json=${_smart_notify_email//\\/\\\\}
    _smart_notify_email_json=${_smart_notify_email_json//\"/\\\"}

    printf '{"discover_nas":%s,"show_volume_info":%s,"show_smart_important":%s,"smart_schedule_enable":%s,"smart_notify_email":"%s","smart_notify_error_only":%s,"manual_nas":[' \
        "$_discover_nas" "$_show_volume_info" "$_show_smart_important" \
        "$_smart_schedule_enable" "$_smart_notify_email_json" "$_smart_notify_error_only"
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

#---------------------------------------------------------------------------
# action=save_settings
# Saves settings from query string to settings.conf.
# Only calls synosetkeyvalue if the value has changed.
# Returns {"ok":true,"changed":true/false}
# Params: discover_nas=true|false
#         manual_nas_count=N
#         manual_nas1=hostname,ip,port  (repeated for each NAS)
#---------------------------------------------------------------------------
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

    # Parse show_volume_info
    _show_volume_info="false"
    if [[ "${QUERY_STRING:-}" =~ (^|&)show_volume_info=([^&]*) ]]; then
        _val="${BASH_REMATCH[2]}"
        [[ "$_val" == "true" ]] && _show_volume_info="true"
    fi

    # Only write show_volume_info if value changed
    _cur_show_volume=$(synogetkeyvalue "$SETTINGS_CONF" show_volume_info 2>/dev/null || echo "")
    if [[ "$_cur_show_volume" != "$_show_volume_info" ]]; then
        synosetkeyvalue "$SETTINGS_CONF" show_volume_info "$_show_volume_info"
        _changed=true
    fi

    # Parse show_smart_important
    _show_smart_important="false"
    if [[ "${QUERY_STRING:-}" =~ (^|&)show_smart_important=([^&]*) ]]; then
        _val="${BASH_REMATCH[2]}"
        [[ "$_val" == "true" ]] && _show_smart_important="true"
    fi

    # Only write show_smart_important if value changed
    _cur_show_smart=$(synogetkeyvalue "$SETTINGS_CONF" show_smart_important 2>/dev/null || echo "")
    if [[ "$_cur_show_smart" != "$_show_smart_important" ]]; then
        synosetkeyvalue "$SETTINGS_CONF" show_smart_important "$_show_smart_important"
        _changed=true
    fi

    # Parse smart_schedule_enable
    _smart_schedule_enable="false"
    if [[ "${QUERY_STRING:-}" =~ (^|&)smart_schedule_enable=([^&]*) ]]; then
        _val="${BASH_REMATCH[2]}"
        [[ "$_val" == "true" ]] && _smart_schedule_enable="true"
    fi

    # Only write smart_schedule_enable if value changed
    _cur_schedule_enable=$(synogetkeyvalue "$SETTINGS_CONF" smart_schedule_enable 2>/dev/null || echo "")
    if [[ "$_cur_schedule_enable" != "$_smart_schedule_enable" ]]; then
        synosetkeyvalue "$SETTINGS_CONF" smart_schedule_enable "$_smart_schedule_enable"
        _changed=true
    fi

    # Parse smart_notify_email (URL-decode %40 -> @, + -> space, same style as manual_nasN)
    _smart_notify_email=""
    if [[ "${QUERY_STRING:-}" =~ (^|&)smart_notify_email=([^&]*) ]]; then
        _smart_notify_email="${BASH_REMATCH[2]}"
        _smart_notify_email="${_smart_notify_email//%40/@}"
        _smart_notify_email="${_smart_notify_email//+/ }"
    fi

    # Only write smart_notify_email if value changed
    _cur_notify_email=$(synogetkeyvalue "$SETTINGS_CONF" smart_notify_email 2>/dev/null || echo "")
    if [[ "$_cur_notify_email" != "$_smart_notify_email" ]]; then
        synosetkeyvalue "$SETTINGS_CONF" smart_notify_email "$_smart_notify_email"
        _changed=true
    fi

    # Parse smart_notify_error_only
    _smart_notify_error_only="false"
    if [[ "${QUERY_STRING:-}" =~ (^|&)smart_notify_error_only=([^&]*) ]]; then
        _val="${BASH_REMATCH[2]}"
        [[ "$_val" == "true" ]] && _smart_notify_error_only="true"
    fi

    # Only write smart_notify_error_only if value changed
    _cur_notify_error_only=$(synogetkeyvalue "$SETTINGS_CONF" smart_notify_error_only 2>/dev/null || echo "")
    if [[ "$_cur_notify_error_only" != "$_smart_notify_error_only" ]]; then
        synosetkeyvalue "$SETTINGS_CONF" smart_notify_error_only "$_smart_notify_error_only"
        _changed=true
    fi

    #-----------------------------------------------------------------------
    # Manage the Task Scheduler entry itself, via the task_scheduler.sh
    # wrapper (run as root through sudo - api.cgi itself runs as the
    # non-root drive_info user, and SYNO.Core.TaskScheduler requires
    # root/admin context to succeed).
    # Strategy: delete-then-recreate whenever any schedule-related setting
    # changed, rather than calling `set` (untested against this webapi).
    #-----------------------------------------------------------------------
    TASK_SCHEDULER_SCRIPT="${TARGET_DIR}/ui/bin/task_scheduler.sh"

    _schedule_settings_changed=false
    if [[ "$_cur_schedule_enable" != "$_smart_schedule_enable" ]] || \
       [[ "$_cur_notify_email" != "$_smart_notify_email" ]] || \
       [[ "$_cur_notify_error_only" != "$_smart_notify_error_only" ]]; then
        _schedule_settings_changed=true
    fi

    if [[ "$_schedule_settings_changed" == "true" ]]; then
        _existing_task_id=$(synogetkeyvalue "$SETTINGS_CONF" smart_schedule_task_id 2>/dev/null || echo "")
        _existing_owner=$(synogetkeyvalue "$SETTINGS_CONF" smart_schedule_owner 2>/dev/null || echo "")

        # Delete existing task if one is on record. Not fatal if it fails
        # (e.g. user already removed it manually via Task Scheduler) -
        # we clear our own record either way.
        if [[ -n "$_existing_task_id" ]]; then
            _delete_result=$(sudo "$TASK_SCHEDULER_SCRIPT" delete "$_existing_task_id" "$_existing_owner" 2>&1)
            # TEMP DEBUG - remove once confirmed working reliably
            {
                echo "--- $(date) delete attempt (whoami: $(whoami)) id=${_existing_task_id} ---"
                echo "$_delete_result"
            } >> "${PKG_ROOT}/var/schedule_debug.log" 2>/dev/null
            synosetkeyvalue "$SETTINGS_CONF" smart_schedule_task_id ""
            synosetkeyvalue "$SETTINGS_CONF" smart_schedule_owner ""
        fi

        # Create a fresh task if the schedule is enabled after this save
        if [[ "$_smart_schedule_enable" == "true" ]]; then
            _notify_enable="false"
            [[ -n "$_smart_notify_email" ]] && _notify_enable="true"

            # -e disables colored text so the output is clean in an email body.
            # -i limits output to important attributes that have increased -
            # only added for the "only when changed" mode. The script's own
            # exit code then differs (non-zero when something increased),
            # which combined with notify_if_error lets DSM only email when
            # something actually changed rather than every day.
            if [[ "$_smart_notify_error_only" == "true" ]]; then
                _smart_script_cmd="${SMART_SCRIPT} -e -i"
            else
                _smart_script_cmd="${SMART_SCRIPT} -e"
            fi

            _create_result=$(sudo "$TASK_SCHEDULER_SCRIPT" create \
                "Drive Info SMART Schedule" "$_smart_script_cmd" \
                "$_notify_enable" "$_smart_notify_error_only" "$_smart_notify_email" 2>&1)
            # TEMP DEBUG: log raw output (incl. stderr) so failures are visible.
            # Remove once schedule create/delete is confirmed working reliably.
            {
                echo "--- $(date) create attempt (whoami: $(whoami)) ---"
                echo "$_create_result"
            } >> "${PKG_ROOT}/var/schedule_debug.log" 2>/dev/null

            _new_id=$(printf '%s' "$_create_result" | jq -r '.data.id // empty' 2>/dev/null)
            if [[ -n "$_new_id" ]]; then
                synosetkeyvalue "$SETTINGS_CONF" smart_schedule_task_id "$_new_id"
                synosetkeyvalue "$SETTINGS_CONF" smart_schedule_owner "root"
            fi
        fi
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

#---------------------------------------------------------------------------
# action=get_ha_passive
# Returns passive node drive data from /var/lib/ha/space_disk_info.
# This file is maintained by the Synology HighAvailability package and
# contains a JSON object of all drives on the passive node, keyed by
# slot id (e.g. "0-1", "0-2", ...).
# Only available on HD6500 / SHA cluster (requires HighAvailability pkg).
#---------------------------------------------------------------------------
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

#---------------------------------------------------------------------------
# action=get_smart
# Returns SMART data for a single drive as HTML fragment.
# Calls smart_info.sh via sudo with the validated device path.
#---------------------------------------------------------------------------
if [[ "$_action" == "get_smart" ]]; then
    printf 'Content-Type: text/html; charset=utf-8\r\n'
    printf 'Access-Control-Allow-Origin: *\r\n'
    printf '\r\n'

    _device=""
    if [[ "${QUERY_STRING:-}" =~ (^|&)device=([^&]*) ]]; then
        _device="${BASH_REMATCH[2]}"
    fi

    # Validate device - must be a known Synology device name pattern
    if [[ ! "$_device" =~ ^(sd[a-z]{1,3}|hd[a-z]{1,3}|sata[0-9]+|sas[0-9]+|nvme[0-9]+n[0-9]+|nvc[0-9]+|usb[0-9]+)$ ]]; then
        echo "<p class=\"err\">$(txt errors err_invalid_device "Invalid device.")</p>"
        exit 0
    fi

    SMART_SCRIPT="${TARGET_DIR}/ui/bin/smart_info.sh"
    if [[ ! -f "$SMART_SCRIPT" ]]; then
        echo "<p class=\"err\">$(txt errors err_smart_script_missing "smart_info.sh not found.")</p>"
        exit 0
    fi

    # Read show_smart_important setting - when true, show only important attributes
    # (default mode); when false/unset, show all attributes (-a flag)
    _smart_important=$(synogetkeyvalue "$SETTINGS_CONF" show_smart_important 2>/dev/null || echo "false")
    SMART_FLAGS=()
    [[ "$_smart_important" != "true" ]] && SMART_FLAGS+=("-a")

    if [[ "$dsm" -ge "7" ]]; then
        SMART_OUTPUT=$(sudo "$SMART_SCRIPT" "${SMART_FLAGS[@]}" --dev="/dev/$_device,$_lang" 2>&1)
    else
        SMART_OUTPUT=$(bash "$SMART_SCRIPT" "${SMART_FLAGS[@]}" --dev="/dev/$_device,$_lang" 2>&1)
    fi
    _smart_rc=$?

    if [[ $_smart_rc -ne 0 ]] && [[ "$SMART_OUTPUT" == *"err::invalid_device"* ]]; then
        echo "<p class=\"err\">$(txt errors err_invalid_device "Invalid device argument.")</p>"
        exit 0
    fi
    if [[ $_smart_rc -ne 0 ]] && [[ "$SMART_OUTPUT" == *"err::invalid_option"* ]]; then
        echo "<p class=\"err\">$(txt errors err_invalid_option "Invalid option.")</p>"
        exit 0
    fi

    #-----------------------------------------------------------------------
    # Parse smart_info.sh sentinel-prefixed output into HTML.
    # Sentinels: green:: red:: yellow:: cyan::  (colour, no row class)
    # Drive header line starts with cyan::Drive / cyan::M.2 Drive / etc.
    # SMART/health lines start with "SMART "
    # -a SATA table: header row contains "ATTRIBUTE_NAME" and "FLAGS"
    # SCSI table: header row contains "ATTRIBUTE_NAME" and "RAW_VALUE" (no FLAGS)
    # NVMe lines: "Key: Value" prose, no leading numeric ID
    # Default table: "  ID Name          Value" two-and-a-bit columns
    #-----------------------------------------------------------------------
    smart_in_table=0
    smart_mode=""        # all_sata | scsi | default
    smart_nvme_open=0

    strip_sentinel() {
        # Sets globals: _row_class (CSS class for <tr>, only set if sentinel is at line start),
        #               _text (line with leading sentinel removed, for line-type detection)
        local l="$1"
        _row_class=""
        case "$l" in
            green::*)  _row_class="smart-green";  l="${l#green::}"  ;;
            red::*)    _row_class="smart-red";     l="${l#red::}"    ;;
            yellow::*) _row_class="smart-yellow";  l="${l#yellow::}" ;;
            cyan::*)   _row_class="smart-cyan";    l="${l#cyan::}"   ;;
            blue::*)   _row_class="smart-blue";    l="${l#blue::}"   ;;
        esac
        _text="$l"
    }

    colorize_inline() {
        # Replaces any green::/red::/yellow::/cyan::/blue:: sentinel anywhere in the line
        # (already HTML-escaped) with a <span class="..."> wrapping the rest of the line.
        local l="$1"
        l="${l//green::/<span class=\"smart-green\">}"
        l="${l//red::/<span class=\"smart-red\">}"
        l="${l//yellow::/<span class=\"smart-yellow\">}"
        l="${l//cyan::/<span class=\"smart-cyan\">}"
        l="${l//blue::/<span class=\"smart-blue\">}"
        if [[ "$l" == *'<span class='* ]]; then
            l="${l}</span>"
        fi
        echo "$l"
    }

    close_smart_table() {
        if [[ $smart_in_table -eq 1 ]]; then
            echo "</tbody></table>"
            smart_in_table=0
            smart_mode=""
        fi
        if [[ $smart_nvme_open -eq 1 ]]; then
            echo "</tbody></table>"
            smart_nvme_open=0
        fi
    }

    while IFS= read -r smart_line; do
        strip_sentinel "$smart_line"
        line="$_text"
        rclass="$_row_class"
        trimmed="${line#"${line%%[![:space:]]*}"}"

        # Blank line - close any open table
        if [[ -z "$trimmed" ]]; then
            close_smart_table
            continue
        fi

        # Drive header line (cyan:: stripped already if present)
        if [[ "$rclass" == "smart-cyan" ]]; then
            close_smart_table
            esc="$(echo "$trimmed" | sed 's/</\&lt;/g;s/>/\&gt;/g')"
            echo "<div id=\"smart-panel-drive-title\" class=\"$rclass\">$esc</div>"
            continue
        fi

        # SMART health / error log prose lines (sentinel may be mid-line, e.g. "...: green::PASSED")
        if [[ "$trimmed" =~ ^SMART ]]; then
            esc="$(echo "$trimmed" | sed 's/</\&lt;/g;s/>/\&gt;/g')"
            esc="$(colorize_inline "$esc")"
            echo "<div id=\"smart-panel-prose\">$esc</div>"
            continue
        fi

        # Separator line - opens a table (header row follows next), some smart_info.sh
        # versions emit one before the header, others don't.
        if [[ "$trimmed" =~ ^-+$ ]]; then
            smart_in_table=1
            smart_mode=""
            continue
        fi

        # Header row for -a (SATA) or SCSI table - detected directly even with no
        # preceding separator line, since some smart_info.sh output omits it.
        if [[ "$trimmed" =~ ATTRIBUTE_NAME ]] && [[ $smart_in_table -eq 0 || -z "$smart_mode" ]]; then
            smart_in_table=1
            if [[ "$trimmed" =~ FLAGS ]]; then
                smart_mode="all_sata"
                echo '<table><thead><tr><th>ID#</th><th>Attribute</th><th>Flags</th><th>Value</th><th>Worst</th><th>Thresh</th><th>Fail</th><th>Raw</th></tr></thead><tbody>'
            elif [[ "$trimmed" =~ RAW_VALUE ]]; then
                smart_mode="scsi"
                echo '<table class="smart-table-compact"><thead><tr><th>ID#</th><th>Attribute</th><th>Raw Value</th></tr></thead><tbody>'
            fi
            continue
        fi

        # Default mode two-column table: "ID Name   RawValue" (sentinel is on the raw value)
        # Must be checked before the generic NVMe colon check, since raw values can
        # themselves contain "::" (e.g. red::368).
        if [[ $smart_in_table -eq 0 ]] && [[ "$trimmed" =~ ^[0-9] ]]; then
            if [[ $smart_nvme_open -eq 0 ]]; then
                echo '<table class="smart-table-compact"><thead><tr><th>ID#</th><th>Attribute</th><th>Raw Value</th></tr></thead><tbody>'
                smart_nvme_open=1
            fi
            esc="$(echo "$trimmed" | sed 's/</\&lt;/g;s/>/\&gt;/g')"
            id="$(echo "$esc" | awk '{print $1}')"
            raw="$(echo "$esc" | awk '{print $NF}')"
            raw="$(colorize_inline "$raw")"
            name="$(echo "$esc" | awk '{$1="";$NF="";print}' | sed 's/^ *//;s/ *$//')"
            name="$(colorize_inline "$name")"
            echo "<tr><td>$id</td><td>$name</td><td>$raw</td></tr>"
            continue
        fi

        # NVMe "Key: Value" prose line (no table context, has a colon, not SMART/Drive line)
        if [[ $smart_in_table -eq 0 ]] && [[ "$trimmed" == *:* ]]; then
            if [[ $smart_nvme_open -eq 0 ]]; then
                echo '<table class="smart-table-compact"><tbody>'
                smart_nvme_open=1
            fi
            key="${trimmed%%:*}"
            val="${trimmed#*:}"
            val="${val#"${val%%[![:space:]]*}"}"
            key="$(echo "$key" | sed 's/</\&lt;/g;s/>/\&gt;/g')"
            val="$(echo "$val" | sed 's/</\&lt;/g;s/>/\&gt;/g')"
            val="$(colorize_inline "$val")"
            row_cls=""
            [[ -n "$rclass" ]] && row_cls=" class=\"smart-row-${rclass#smart-}\""
            echo "<tr${row_cls}><td>$key</td><td>$val</td></tr>"
            continue
        fi

        # Table data rows
        if [[ $smart_in_table -eq 1 ]]; then
            esc="$(echo "$trimmed" | sed 's/</\&lt;/g;s/>/\&gt;/g')"
            row_cls=""
            [[ -n "$rclass" ]] && row_cls=" class=\"smart-row-${rclass#smart-}\""
            if [[ "$smart_mode" == "all_sata" ]]; then
                # ID# ATTRIBUTE_NAME FLAGS VALUE WORST THRESH FAIL RAW_VALUE
                IFS='|' read -r id name flags value worst thresh fail raw <<< "$(echo "$esc" | awk '{id=$1;name=$2;flags=$3;value=$4;worst=$5;thresh=$6;fail=$7;$1=$2=$3=$4=$5=$6=$7="";raw=$0;sub(/^ +/,"",raw);printf "%s|%s|%s|%s|%s|%s|%s|%s",id,name,flags,value,worst,thresh,fail,raw}')"
                echo "<tr${row_cls}><td>$id</td><td>$name</td><td>$flags</td><td>$value</td><td>$worst</td><td>$thresh</td><td>$fail</td><td>$raw</td></tr>"
            elif [[ "$smart_mode" == "scsi" ]]; then
                # ID# ATTRIBUTE_NAME (multi-word) RAW_VALUE - take first and last field, middle is name
                id="$(echo "$esc" | awk '{print $1}')"
                raw="$(echo "$esc" | awk '{print $NF}')"
                name="$(echo "$esc" | awk '{$1="";$NF="";print}' | sed 's/^ *//;s/ *$//')"
                echo "<tr${row_cls}><td>$id</td><td>$name</td><td>$raw</td></tr>"
            fi
            continue
        fi

        # Fallback - unknown line format, show as-is
        esc="$(echo "$trimmed" | sed 's/</\&lt;/g;s/>/\&gt;/g')"
        echo "<div>$esc</div>"

    done <<< "$SMART_OUTPUT"
    close_smart_table

    exit 0
fi

#---------------------------------------------------------------------------
# Default action: render main page HTML
# Settings are embedded in the same page and shown/hidden via JS.
#---------------------------------------------------------------------------
printf 'Content-Type: text/html; charset=utf-8\r\n'
printf 'Access-Control-Allow-Origin: *\r\n'
printf '\r\n'

# Read settings
_discover_nas=$(synogetkeyvalue "$SETTINGS_CONF" discover_nas 2>/dev/null || echo "false")
_show_volume_info=$(synogetkeyvalue "$SETTINGS_CONF" show_volume_info 2>/dev/null || echo "true")
_manual_count=$(synogetkeyvalue "$SETTINGS_CONF" manual_nas_count 2>/dev/null || echo "0")
_show_smart_important=$(synogetkeyvalue "$SETTINGS_CONF" show_smart_important 2>/dev/null || echo "true")
_smart_schedule_enable=$(synogetkeyvalue "$SETTINGS_CONF" smart_schedule_enable 2>/dev/null || echo "false")
_smart_notify_email=$(synogetkeyvalue "$SETTINGS_CONF" smart_notify_email 2>/dev/null || echo "")
_smart_notify_error_only=$(synogetkeyvalue "$SETTINGS_CONF" smart_notify_error_only 2>/dev/null || echo "false")
[[ -z "$_show_smart_important" ]] && _show_smart_important="false"
[[ -z "$_discover_nas" ]] && _discover_nas="false"
[[ -z "$_show_volume_info" ]] && _show_volume_info="false"
[[ -z "$_smart_schedule_enable" ]] && _smart_schedule_enable="false"
[[ -z "$_smart_notify_error_only" ]] && _smart_notify_error_only="false"
[[ -z "$_manual_count" ]] && _manual_count="0"

# Escape email for safe embedding in HTML attribute (value="...") and JS string literal
_smart_notify_email_attr=${_smart_notify_email//&/&amp;}
_smart_notify_email_attr=${_smart_notify_email_attr//\"/&quot;}
_smart_notify_email_js=${_smart_notify_email//\\/\\\\}
_smart_notify_email_js=${_smart_notify_email_js//\'/\\\'}

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
_txt_discover=$(txt settings discover_local_nas "Find all local Synology NAS")
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
_txt_reload=$(txt common reload "Reload")
_txt_slot=$(txt common drive_id "Drive ID")
_txt_model=$(txt common model "Model")
_txt_size=$(txt common size "Size")
_txt_smr=$(txt common size "SMR")
_txt_size=$(txt common raid_type "RAID")
_txt_serial=$(txt common serial_number "Serial Number")
_txt_temp=$(txt common temperature "Temperature")
#_txt_temp=$(txt common temperature "°C")
_txt_status=$(txt common status "Status")
_txt_volume=$(txt common volume "Volume")
_txt_smart_view=$(txt common smart_view "View S.M.A.R.T.")
_txt_show_volume_info=$(txt settings show_volume_info "Show volume information")
_txt_show_smart_important=$(txt settings show_smart_important "Show only important S.M.A.R.T. values")
_txt_smart_schedule_enable=$(txt settings smart_schedule_enable "Schedule daily S.M.A.R.T. emails (midnight)")
_txt_notify_email=$(txt settings notify_email "Notification email")
_txt_notify_error_only=$(txt settings notify_error_only "Only email when important attributes have changed")
_txt_not_reachable=$(txt errors err_not_reachable "Drive Info not installed or not reachable.")
_txt_smart_timeout=$(txt errors err_smart_timeout "Timed out waiting for SMART data. The NAS may be busy (e.g. running a data scrub or parity check) - try again shortly.")
_txt_smart_failed=$(txt errors err_smart_failed "Request failed.")
_txt_lang="$_lang"   # or gui_lang, whatever you settle on

cat << STYLE
<style>
body { font-family: Verdana, Arial, sans-serif; font-size: 13px; color: #333;
       margin: 16px; margin-right: 14px; background: transparent; overflow-y: auto; overflow-x: auto; }
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
col.size     { width: 6%; min-width: 30px; }
col.smr      { width: 2%; min-width: 10px; }
col.raid     { width: 4%; min-width: 20px; }
col.serial   { width: 20%; min-width: 75px; }
col.temp     { width: 8%; min-width: 40px; }
col.status   { width: auto; min-width: 110px; }
th.id, td.id             { white-space: nowrap; }
th.num, td.num           { white-space: nowrap; }
th.location, td.location { white-space: nowrap; }
th.model, td.model       { white-space: nowrap; }
th.size, td.size         { white-space: nowrap; }
th.smr, td.smr           { white-space: nowrap; }
th.raid, td.raid         { white-space: nowrap; }
th.serial, td.serial     { white-space: nowrap; }
th.temp, td.temp         { white-space: nowrap; }
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
.vol-table-wrapper { margin-top: 8px; }
col.vol-name   { width: 12%; min-width: 80px; }
col.vol-pool   { width: 18%; min-width: 110px; }
col.vol-size   { width: 12%; min-width: 80px; }
col.vol-used   { width: 10%; min-width: 60px; }
col.vol-pool-status { width: auto; min-width: 100px; }
td.vol-name    { color: #057FEB; white-space: nowrap; }
td.vol-pool    { white-space: nowrap; }
td.vol-size    { white-space: nowrap; }
td.vol-used    { white-space: nowrap; }
td.vol-pool-status { white-space: nowrap; }
th.vol-name, th.vol-pool, th.vol-size, th.vol-used, th.vol-pool-status { white-space: nowrap; }
.err { color: #c00; }
a    { color: #0073c0; }
/* Top bar - shared by both views */
.topbar { display: flex; justify-content: flex-end; align-items: center; gap: 10px; margin-bottom: 4px; padding-right: 8px; }
.icon-btn { background: #e8eef3; border: 1px solid #e8eef3; border-radius: 4px;
            cursor: pointer; padding: 4px 10px; line-height: 0; }
.icon-btn:hover { background: #e8eef3; border-color: #aaa; }
.icon-btn:disabled { cursor: default; border-color: #e8eef3; }
.icon-btn:disabled:hover { border-color: #e8eef3; }
.icon-btn:disabled img { content: url('/webman/3rdparty/drive_info/images/bt_gear_disabled.png'); }
#reload-btn:disabled img { content: url('/webman/3rdparty/drive_info/images/bt_reload_disabled.png'); }
/* Remote NAS sections */
.remote-section { margin-top: 20px; }
#ha-passive-container { margin-top: 20px; }
.remote-section h2 { color: #333; }
.remote-err { color: #999; font-size: 12px; font-style: italic; }
/* Settings panel */
.section { margin-bottom: 20px; }
.section-title { font-size: 13px; font-weight: bold; color: #555;
                 margin-bottom: 8px; border-bottom: 1px solid #eee;
                 padding-bottom: 4px; padding-left: 10px; }
.toggle-row { display: flex; align-items: center; gap: 10px; padding: 6px 0; }
#discover-row { padding-left: 8px; }
#volume-info-row { padding-left: 8px; }
#smart-important-row { padding-left: 8px; }
#smart-schedule-row { padding-left: 8px; }
#smart-error-only-row { padding-left: 8px; }
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
/* SMART panel */
.smart-btn { background: none; border: none; cursor: pointer;
             font-family: Verdana, Arial, sans-serif; font-size: 13px;
             padding: 0; text-decoration: underline dotted; }
.smart-btn.status-healthy  { color: #1CA600; }
.smart-btn.status-warning  { color: #FF7F00; }
.smart-btn.status-critical { color: #E64040; }
.smart-btn.status-failing  { color: #E64040; }
.smart-btn.status          { color: #333; }
#smart-panel { position: fixed; top: 0; right: 0; width: auto; max-width: 100%;
               min-width: 430px;
               height: 100%; background: white; box-shadow: -2px 0 8px rgba(0,0,0,0.15);
               transform: translateX(100%); transition: transform 0.25s ease; z-index: 1000;
               overflow-y: auto; overflow-x: auto; padding: 16px; box-sizing: border-box; }
#smart-panel.open { transform: translateX(0); }
#smart-panel h3 { margin-top: 0; font-size: 14px; color: #333; }
#smart-panel-topbar { display: flex; justify-content: flex-end;
                      margin-bottom: 4px; padding-right: 8px; }
.smart-cyan { color: #057FEB; }
.smart-green  { color: #1CA600; }
.smart-red    { color: #E64040; }
.smart-yellow { color: #FF7F00; }
.smart-blue   { color: #0073c0; }
#smart-panel-drive-title { font-size: 14px; font-weight: bold; margin-bottom: 14px; white-space: nowrap; }
#smart-panel-prose { font-size: 12px; color: #555; margin: 2px 0 10px 0; white-space: nowrap; }
#smart-panel table { width: auto; min-width: 100%; border-collapse: collapse;
                      margin-top: 6px; table-layout: auto; }
#smart-panel table.smart-table-compact { min-width: 0; }
#smart-panel th, #smart-panel td { white-space: nowrap; }
#smart-panel th { text-align: left; padding: 4px 8px; border-bottom: 2px solid #ccc; color: #555; }
#smart-panel td { padding: 3px 8px; border-bottom: 1px solid #eee; }
#smart-panel tr.smart-row-yellow td { background: #fff6e8; }
#smart-panel tr.smart-row-red td { background: #fdeaea; }
#smart-panel tr.smart-row-green td { background: #eefcea; }
#smart-panel tr.smart-row-blue td { background: #eaf4fc; }
#smart-panel td, #smart-panel th { padding: 3px 8px; }
#smart-panel .smart-fail { color: #E64040; font-weight: bold; }
#smart-overlay { display: none; position: fixed; top: 0; left: 0;
                 width: 100%; height: 100%; z-index: 999; }
#smart-overlay.open { display: block; }
</style>
STYLE

#---------------------------------------------------------------------------
# Top bar - single button that toggles between gear and home
#---------------------------------------------------------------------------
cat << TOPBAR
<div class="topbar">
  <button class="icon-btn" id="reload-btn"
          onclick="reloadPage()"
          title="${_txt_reload}" disabled><img src="/webman/3rdparty/drive_info/images/bt_reload.png" width="20" height="20" alt=""></button>
  <button class="icon-btn" id="nav-btn"
          onclick="showSettings()"
          title="${_txt_settings}" disabled><img src="/webman/3rdparty/drive_info/images/bt_gear.png" width="20" height="20" alt=""></button>
</div>
TOPBAR

#---------------------------------------------------------------------------
# Main view
#---------------------------------------------------------------------------
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
if [[ "$dsm" -ge "7" ]]; then
    if ! sudo -n -l "$SCRIPT" >/dev/null 2>&1; then
        cat << NOPERMS
<h2 style="color:#c00;">$(txt errors err_noperms_title "Permissions not configured")</h2>
<p>$(txt errors err_noperms_desc "This package needs elevated permissions to read drive information.")</p>
<p>$(txt errors err_see_details "See <a href=\"https://github.com/007revad/Synology_drive_info/blob/main/set_package_permissions.md\" target=\"_blank\">set_package_permissions.md</a> for full details.")</p>
</div>
<script>document.getElementById("nav-btn").disabled=false;document.getElementById("reload-btn").disabled=false;</script>
NOPERMS
        exit 0
    fi
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
    document.getElementById('nav-btn').disabled = false;
    document.getElementById('reload-btn').disabled = false;
}

function reloadPage() {
    window.location.href = 'api.cgi?_ts=' + new Date().getTime();
}
</script>
SPINNER

# Flush spinner to browser before running the slow script
dd if=/dev/zero bs=4096 count=1 2>/dev/null | tr '\0' ' '

# Run drive_info.sh as root via sudo
STDERR_TMP=$(mktemp)
OUTPUT=$(sudo "${SCRIPT}" "$_lang" 2>"$STDERR_TMP")

EXIT_CODE=$?
STDERR_OUT=$(cat "$STDERR_TMP")
rm -f "$STDERR_TMP"

# Clear spinner and enable settings button
echo '<script>document.getElementById("loading").style.display="none";document.getElementById("nav-btn").disabled=false;document.getElementById("reload-btn").disabled=false;</script>'

# Check if sudo failed
if [[ "$dsm" -ge "7" ]]; then
    if echo "$STDERR_OUT" | grep -qi "not in the sudoers\|sudoers file\|not allowed\|password is required"; then
        cat << SUDOFAIL
<h2 style="color:#c00;">$(txt errors err_sudofail_title "Permissions not configured correctly")</h2>
<p>$(txt errors err_sudofail_desc "The sudoers entry exists but sudo failed. Check the entry is correct:")</p>
<pre>cat $SUDOERS_FILE</pre>
<p>$(txt errors err_see_details "See <a href=\"https://github.com/007revad/Synology_drive_info/blob/main/set_package_permissions.md\" target=\"_blank\">set_package_permissions.md</a> for full details.")</p>
</div>
SUDOFAIL
        exit 0
    fi
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
table_type=""   # "drive" or "volume"
headers=()
col_count=0

# Pre-scan to check if any Location column values are non-empty
HAS_LOCATION=0
IS_SMR=0
scan_in_table=0
scan_skip=0
scan_headers=()
scan_col_starts=()
scan_col_count=0
while IFS= read -r line; do
    trimmed="${line#"${line%%[![:space:]]*}"}"
    if [[ "$trimmed" =~ ^-+$ ]]; then
        scan_in_table=1; continue
    fi

    # Skip table - silently consume rows until the blank line that ends it.
    # (Without this, the dashed separator after a skipped header would flip
    # scan_in_table back on and the next data row would be misread as a
    # fresh header row.)
    if [[ $scan_in_table -eq 1 ]] && [[ $scan_skip -eq 1 ]] && [[ -n "$trimmed" ]]; then
        continue
    fi
    if [[ $scan_in_table -eq 1 ]] && [[ $scan_skip -eq 1 ]] && [[ -z "$trimmed" ]]; then
        scan_in_table=0; scan_skip=0; continue
    fi

    if [[ $scan_in_table -eq 1 ]] && [[ ${#scan_headers[@]} -eq 0 ]] && [[ -n "$trimmed" ]]; then
        IFS=$'\n' read -r -d '' -a scan_headers <<< "$(echo "$trimmed" | grep -oP '\S.*?(?=  |\s*$)')" || true
        scan_col_count=${#scan_headers[@]}
        # Only check Location for drive tables (first header is not "Volume")
        if [[ "${scan_headers[0]}" == "$_txt_volume" ]]; then
            scan_skip=1; scan_headers=(); continue
        fi
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
        if [[ $HAS_LOCATION -eq 0 ]]; then
            start="${scan_col_starts[2]}"
            if (( 3 < scan_col_count )); then
                len=$(( scan_col_starts[3] - start - 2 ))
            else
                len=$(( ${#line} - start ))
            fi
            val="${line:$start:$len}"
            val="${val%"${val##*[![:space:]]}"}"
            [[ -n "$val" ]] && HAS_LOCATION=1
        fi

        if [[ $IS_SMR -eq 0 ]] && (( scan_col_count > 5 )); then
            start="${scan_col_starts[5]}"
            if (( 6 < scan_col_count )); then
                len=$(( scan_col_starts[6] - start - 2 ))
            else
                len=$(( ${#line} - start ))
            fi
            smr_val="${line:$start:$len}"
            smr_val="${smr_val%"${smr_val##*[![:space:]]}"}"
            [[ -n "$smr_val" ]] && IS_SMR=1
        fi

        if [[ $HAS_LOCATION -eq 1 && $IS_SMR -eq 1 ]]; then break; fi
        continue
    fi

    if [[ $scan_in_table -eq 1 ]] && [[ ${#scan_headers[@]} -gt 0 ]] && [[ -z "$trimmed" ]]; then
        scan_in_table=0; scan_headers=(); continue
    fi
done <<< "$OUTPUT"

while IFS= read -r line; do
    trimmed="${line#"${line%%[![:space:]]*}"}"

    # Separator line — starts a new table
    if [[ "$trimmed" =~ ^-+$ ]]; then
        if [[ $in_table -eq 0 ]]; then
            in_table=1
            table_type=""  # determined when we read the header row
        fi
        continue
    fi

    # Skip table - silently consume data rows
    if [[ $in_table -eq 1 ]] && [[ "$table_type" == "skip" ]] && [[ -n "$trimmed" ]]; then continue; fi

    # Skip table - blank line ends the skip
    if [[ $in_table -eq 1 ]] && [[ "$table_type" == "skip" ]] && [[ -z "$trimmed" ]]; then
        in_table=0; table_type=""; continue
    fi

    # Header row
    if [[ $in_table -eq 1 ]] && [[ ${#headers[@]} -eq 0 ]] && [[ -n "$trimmed" ]]; then
        IFS=$'\n' read -r -d '' -a headers <<< "$(echo "$trimmed" | grep -oP '\S.*?(?=  |\s*$)')" || true
        col_count=${#headers[@]}

        col_starts=()
        pos=0
        for h in "${headers[@]}"; do
            rest="${line:$pos}"
            prefix="${rest%%"$h"*}"
            col_starts+=("$(( pos + ${#prefix} ))")
            pos=$(( pos + ${#prefix} + ${#h} ))
        done

        # Detect table type by first header
        if [[ "${headers[0]}" == "$_txt_volume" ]]; then
            table_type="volume"
            if [[ "$_show_volume_info" != "true" ]]; then
                # Skip volume table entirely
                in_table=1; table_type="skip"; headers=(); continue
            fi
            echo '<div class="vol-table-wrapper"><table class="vol-table"><colgroup><col class="vol-name"><col class="vol-pool"><col class="raid"><col class="vol-size"><col class="vol-used"><col class="status"><col class="vol-pool-status"></colgroup>'
        else
            table_type="drive"
            if [[ $HAS_LOCATION -eq 1 && $IS_SMR -eq 1 ]]; then
                echo '<table><colgroup><col class="id"><col class="num"><col class="location"><col class="model"><col class="size"><col class="smr"><col class="serial"><col class="temp"><col class="status"></colgroup>'
            elif [[ $HAS_LOCATION -eq 1 ]]; then
                echo '<table><colgroup><col class="id"><col class="num"><col class="location"><col class="model"><col class="size"><col class="serial"><col class="temp"><col class="status"></colgroup>'
            elif [[ $IS_SMR -eq 1 ]]; then
                echo '<table><colgroup><col class="id"><col class="num"><col class="model"><col class="size"><col class="smr"><col class="serial"><col class="temp"><col class="status"></colgroup>'
            else
                echo '<table><colgroup><col class="id"><col class="num"><col class="model"><col class="size"><col class="serial"><col class="temp"><col class="status"></colgroup>'
            fi
        fi

        echo "<thead><tr>"
        if [[ "$table_type" == "volume" ]]; then
            vol_classes=("vol-name" "vol-pool" "raid" "vol-size" "vol-used" "status" "vol-pool-status")
            for idx in "${!headers[@]}"; do
                cls="${vol_classes[$idx]:-}"
                echo "<th class=\"$cls\">$(echo "${headers[$idx]}" | sed 's/</\&lt;/g;s/>/\&gt;/g')</th>"
            done
        else
            col_classes=("id" "num" "location" "model" "size" "smr" "serial" "temp" "status")
            for idx in "${!headers[@]}"; do
                cls="${col_classes[$idx]:-}"
                [[ "$cls" == "location" && $HAS_LOCATION -eq 0 ]] && continue
                [[ "$cls" == "smr" && $IS_SMR -eq 0 ]] && continue
                echo "<th class=\"$cls\">$(echo "${headers[$idx]}" | sed 's/</\&lt;/g;s/>/\&gt;/g')</th>"
            done
        fi
        echo "</tr></thead><tbody>"
        continue
    fi

    # Data row
    if [[ $in_table -eq 1 ]] && [[ ${#headers[@]} -gt 0 ]] && [[ -n "$trimmed" ]]; then
        echo "<tr>"
        for (( c=0; c<col_count; c++ )); do
            start="${col_starts[$c]}"
            if (( c + 1 < col_count )); then
                len=$(( col_starts[c+1] - start - 2 ))
            else
                len=$(( ${#line} - start ))
            fi
            val="${line:$start:$len}"
            val="${val%"${val##*[![:space:]]}"}"
            val="$(echo "$val" | sed 's/</\&lt;/g;s/>/\&gt;/g')"

            if [[ "$table_type" == "volume" ]]; then
                case $c in
                    0) echo "<td class=\"vol-name\">$val</td>" ;;
                    1) echo "<td class=\"vol-pool\">$val</td>" ;;
                    2)
                        if [[ "$val" == *"@@"* ]]; then
                            raid_label="${val%%@@*}"
                            raid_disks="${val#*@@}"
                            raid_disks="${raid_disks//\"/&quot;}"
                            echo "<td class=\"raid\" title=\"${raid_disks}\">${raid_label}</td>"
                        else
                            echo "<td class=\"raid\">$val</td>"
                        fi
                        ;;
                    3) echo "<td class=\"vol-size\">$val</td>" ;;
                    4) echo "<td class=\"vol-used\">$val</td>" ;;
                    5)
                        case "$val" in
                            healthy::*)  css_class="status-healthy";  val="${val#healthy::}"  ;;
                            warning::*)  css_class="status-warning";  val="${val#warning::}"  ;;
                            critical::*) css_class="status-critical"; val="${val#critical::}" ;;
                            failing::*)  css_class="status-failing";  val="${val#failing::}"  ;;
                            *)           css_class="status"                                   ;;
                        esac
                        css_class="$css_class status"
                        echo "<td class=\"$css_class\">$val</td>"
                        ;;
                    6)
                        case "$val" in
                            healthy::*)  css_class="status-healthy";  val="${val#healthy::}"  ;;
                            warning::*)  css_class="status-warning";  val="${val#warning::}"  ;;
                            critical::*) css_class="status-critical"; val="${val#critical::}" ;;
                            failing::*)  css_class="status-failing";  val="${val#failing::}"  ;;
                            *)           css_class="vol-pool-status"                          ;;
                        esac
                        css_class="$css_class vol-pool-status"
                        if [[ "$val" == *" - "* ]]; then
                            val_main="${val%% - *}"
                            val_suffix=" - ${val#* - }"
                            echo "<td class=\"$css_class\">${val_main}<span style=\"color:var(--text-color,#000)\">${val_suffix}</span></td>"
                        else
                            echo "<td class=\"$css_class\">$val</td>"
                        fi                        ;;
                    *) echo "<td>$val</td>" ;;
                esac
            else
                if [[ $c -eq 0 ]]; then
                    echo "<td class=\"id\">$val</td>"
                elif [[ $c -eq 1 ]]; then
                    if [[ "$val" == *"@@"* ]]; then
                        num_label="${val%%@@*}"
                        num_pool="${val#*@@}"
                        num_pool="${num_pool//\"/&quot;}"
                        echo "<td class=\"num\" title=\"${num_pool}\">${num_label}</td>"
                    else
                        echo "<td class=\"num\">$val</td>"
                    fi
                elif [[ $c -eq 2 ]]; then
                    [[ $HAS_LOCATION -eq 0 ]] && continue
                    echo "<td class=\"location\">$val</td>"
                elif [[ $c -eq 3 ]]; then
                    echo "<td class=\"model\">$val</td>"
                elif [[ $c -eq 4 ]]; then
                    echo "<td class=\"size\">$val</td>"
                elif [[ $c -eq 5 ]]; then
                    [[ $IS_SMR -eq 0 ]] && continue
                    echo "<td class=\"smr\">$val</td>"
                elif [[ $c -eq 6 ]]; then
                    echo "<td class=\"serial\">$val</td>"
                elif [[ $c -eq 7 ]]; then
                    #echo "<td class=\"temp\">${val}°C</td>"
                    echo "<td class=\"temp\">${val}</td>"
                elif [[ $c -eq 8 ]]; then
                    case "$val" in
                        healthy::*)  css_class="status-healthy";  val="${val#healthy::}"  ;;
                        warning::*)  css_class="status-warning";  val="${val#warning::}"  ;;
                        critical::*) css_class="status-critical"; val="${val#critical::}" ;;
                        failing::*)  css_class="status-failing";  val="${val#failing::}"  ;;
                        *)           css_class="status"                                   ;;
                    esac
                    echo "<td class=\"$css_class\"><button class=\"smart-btn $css_class\" onclick=\"showSmartPanel(this)\" title=\"${_txt_smart_view}\">$val</button></td>"
                else
                    echo "<td>$val</td>"
                fi
            fi
        done
        echo "</tr>"
        continue
    fi

    # Blank line ends table
    if [[ $in_table -eq 1 ]] && [[ ${#headers[@]} -gt 0 ]] && [[ -z "$trimmed" ]]; then
        if [[ "$table_type" == "volume" ]]; then
            echo "</tbody></table></div>"
        elif [[ "$table_type" == "drive" ]] && [[ "$_show_volume_info" == "true" ]]; then
            echo "</tbody></table>"
        else
            echo "</tbody></table><br>"
        fi
        in_table=0; table_type=""; headers=(); continue
    fi
done <<< "$OUTPUT"

if [[ $in_table -eq 1 ]]; then
    if [[ "$table_type" == "volume" ]]; then
        echo "</tbody></table></div>"
    else
        echo "</tbody></table>"
    fi
fi

# Remote NAS container - populated by JS after page load
echo '<div id="remote-nas-container"></div>'

# HA passive node container - populated by JS after page load
echo '<div id="ha-passive-container"></div>'

# SMART info panel
echo "<div id=\"smart-overlay\" onclick=\"closeSmartPanel()\"></div>"
echo "<div id=\"smart-panel\"><div id=\"smart-panel-topbar\"><button class=\"icon-btn\" onclick=\"closeSmartPanel()\" title=\"${_txt_back}\"><img src=\"/webman/3rdparty/drive_info/images/bt_home.png\" width=\"20\" height=\"20\" alt=\"\"></button></div><div id=\"smart-panel-content\"></div></div>"

# Close main-view div
echo '</div>'

#---------------------------------------------------------------------------
# Settings panel - hidden until gear button clicked
#---------------------------------------------------------------------------
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
    <div class="toggle-row" id="volume-info-row">
      <label class="toggle">
        <input type="checkbox" id="show_volume_info" $([ "$_show_volume_info" = "true" ] && echo "checked")>
        <span class="toggle-slider"></span>
      </label>
      <span>${_txt_show_volume_info}</span>
    </div>
    <div class="toggle-row" id="smart-important-row">
      <label class="toggle">
        <input type="checkbox" id="show_smart_important" $([ "$_show_smart_important" = "true" ] && echo "checked")>
        <span class="toggle-slider"></span>
      </label>
      <span>${_txt_show_smart_important}</span>
    </div>
    <div class="toggle-row" id="smart-schedule-row">
      <label class="toggle">
        <input type="checkbox" id="smart_schedule_enable" onchange="toggleScheduleFields()" $([ "$_smart_schedule_enable" = "true" ] && echo "checked")>
        <span class="toggle-slider"></span>
      </label>
      <span>${_txt_smart_schedule_enable}</span>
    </div>
    <div class="schedule-subfields" id="schedule-subfields" style="$([ "$_smart_schedule_enable" = "true" ] || echo "display:none;")">
      <div class="field-row" style="margin-left:58px;margin-top:7px;margin-bottom:7px;display:flex;align-items:center;gap:10px;">
        <label for="smart_notify_email" style="font-size:13px;white-space:nowrap;">${_txt_notify_email}</label>
        <input type="email" id="smart_notify_email" value="${_smart_notify_email_attr}" style="width:300px;font-size:13px;padding:3px 5px;border:1px solid #ccc;">
      </div>
      <div class="toggle-row" id="smart-error-only-row" style="margin-left:50px;">
        <label class="toggle">
          <input type="checkbox" id="smart_notify_error_only" $([ "$_smart_notify_error_only" = "true" ] && echo "checked")>
          <span class="toggle-slider"></span>
        </label>
        <span>${_txt_notify_error_only}</span>
      </div>
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

#---------------------------------------------------------------------------
# JavaScript - settings panel + remote NAS fetching
#---------------------------------------------------------------------------
cat << JAVASCRIPT
<script>
var nasData = ${_manual_json};
var nasDataSaved = JSON.parse(JSON.stringify(nasData));  // snapshot for Cancel
var discoverNasSaved = ${_discover_nas};                 // snapshot for Cancel
var showVolumeInfoSaved = ${_show_volume_info};          // snapshot for Cancel
var showImportantSMART = ${_show_smart_important};       // snapshot for Cancel
var smartScheduleEnableSaved = ${_smart_schedule_enable};      // snapshot for Cancel
var smartNotifyEmailSaved = '${_smart_notify_email_js}';       // snapshot for Cancel
var smartNotifyErrorOnlySaved = ${_smart_notify_error_only};   // snapshot for Cancel
var txtRemove = "${_txt_remove}";
var viewer_lang = '${_lang}';
var dirty = false;  // true only after settings have been saved

// ---------------------------------------------------------------------------
// Settings panel show/hide
// ---------------------------------------------------------------------------
function showSettings() {
    document.getElementById('main-view').style.display = 'none';
    document.getElementById('settings-panel').style.display = '';
    document.getElementById('reload-btn').style.display = 'none';
    var btn = document.getElementById('nav-btn');
    btn.innerHTML = '<img src="/webman/3rdparty/drive_info/images/bt_home.png" width="20" height="20" alt="">';
    btn.title = '${_txt_back}';
    btn.onclick = cancelSettings;
    renderTable();
}

function cancelSettings() {
    // Discard any unsaved changes by re-reading from the last-saved nasData snapshot
    nasData = JSON.parse(JSON.stringify(nasDataSaved));
    document.getElementById('discover_nas').checked = discoverNasSaved;
    document.getElementById('show_volume_info').checked = showVolumeInfoSaved;
    document.getElementById('show_smart_important').checked = showImportantSMART;
    document.getElementById('smart_schedule_enable').checked = smartScheduleEnableSaved;
    document.getElementById('smart_notify_email').value = smartNotifyEmailSaved;
    document.getElementById('smart_notify_error_only').checked = smartNotifyErrorOnlySaved;
    toggleScheduleFields();
    document.getElementById('settings-panel').style.display = 'none';
    document.getElementById('main-view').style.display = '';
    document.getElementById('reload-btn').style.display = '';
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

// ---------------------------------------------------------------------------
// Show/hide the email + error-only fields under the schedule toggle
// ---------------------------------------------------------------------------
function toggleScheduleFields() {
    var enabled = document.getElementById('smart_schedule_enable').checked;
    document.getElementById('schedule-subfields').style.display = enabled ? '' : 'none';
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
    var showVolumeInfo = document.getElementById('show_volume_info').checked ? 'true' : 'false';
    var showSmartImportant = document.getElementById('show_smart_important').checked ? 'true' : 'false';
    var smartScheduleEnable = document.getElementById('smart_schedule_enable').checked ? 'true' : 'false';
    var smartNotifyEmail = document.getElementById('smart_notify_email').value.trim();
    var smartNotifyErrorOnly = document.getElementById('smart_notify_error_only').checked ? 'true' : 'false';
    var qs = 'action=save_settings&discover_nas=' + discover +
             '&show_volume_info=' + showVolumeInfo +
             '&show_smart_important=' + showSmartImportant +
             '&smart_schedule_enable=' + smartScheduleEnable +
             '&smart_notify_email=' + encodeURIComponent(smartNotifyEmail) +
             '&smart_notify_error_only=' + smartNotifyErrorOnly +
             '&manual_nas_count=' + valid.length;

    for (var j = 0; j < valid.length; j++) {
        qs += '&manual_nas' + (j + 1) + '=' + encodeURIComponent(valid[j]);
    }

    // Only a change to show_smart_important needs no full reload, since it only
    // affects the on-demand SMART panel fetch, not the main drive table.
    var validSaved = [];
    for (var k = 0; k < nasDataSaved.length; k++) {
        var sh = (nasDataSaved[k].hostname || '').trim();
        var sip = (nasDataSaved[k].ip || '').trim();
        var sport = (nasDataSaved[k].port || '').trim() || '5000';
        var sen = nasDataSaved[k].enabled !== false;
        if (sh === '' && sip === '') continue;
        validSaved.push(sh + ',' + sip + ',' + sport + ',' + (sen ? '1' : '0'));
    }
    var nasChanged = JSON.stringify(valid) !== JSON.stringify(validSaved);
    var needsReload = (discover !== String(discoverNasSaved)) ||
                       (showVolumeInfo !== String(showVolumeInfoSaved)) ||
                       nasChanged;

    var xhr = new XMLHttpRequest();
    xhr.open('GET', 'api.cgi?' + qs, true);
    xhr.onreadystatechange = function() {
        if (xhr.readyState === 4) {
            if (needsReload) {
                window.location.href = 'api.cgi?_ts=' + new Date().getTime();
            } else {
                // Update saved snapshots in place and return to main view without reload
                showImportantSMART = (showSmartImportant === 'true');
                nasDataSaved = JSON.parse(JSON.stringify(nasData));
                discoverNasSaved = (discover === 'true');
                showVolumeInfoSaved = (showVolumeInfo === 'true');
                smartScheduleEnableSaved = (smartScheduleEnable === 'true');
                smartNotifyEmailSaved = smartNotifyEmail;
                smartNotifyErrorOnlySaved = (smartNotifyErrorOnly === 'true');
                document.getElementById('settings-panel').style.display = 'none';
                document.getElementById('main-view').style.display = '';
                document.getElementById('reload-btn').style.display = '';
                var btn = document.getElementById('nav-btn');
                btn.innerHTML = '<img src="/webman/3rdparty/drive_info/images/bt_gear.png" width="20" height="20" alt="">';
                btn.title = '${_txt_settings}';
                btn.onclick = showSettings;
                var fb = document.getElementById('save-feedback');
                fb.style.opacity = '1';
                setTimeout(function(){ fb.style.opacity = '0'; }, 1500);
            }
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
    section.dataset.apiBase = url;
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
    var sep = url.indexOf('?') >= 0 ? '&' : '?';
    var fxhr = new XMLHttpRequest();
    fxhr.open('GET', url + sep + 'lang=' + encodeURIComponent(viewer_lang), true);
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
            html = html.replace(/<div id="smart-overlay"[^>]*>[\s\S]*?<\/div>/gi, '');
            html = html.replace(/<div id="smart-panel"[\s\S]*?<\/div>\s*<\/div>/gi, '');
            html = html.replace(/<h2>[\s\S]*?<\/h2>/gi, '');
            section.innerHTML += html;
        } else {
            section.innerHTML += '<p class="remote-err">HTTP ' + fxhr.status + '</p>';
        }
    };
    fxhr.onerror = function() {
        var sp = section.querySelector('.nas-spinner');
        if (sp) sp.parentNode.removeChild(sp);
        section.innerHTML += '<p class="remote-err">${_txt_not_reachable}</p>';
    };
    fxhr.send();
}

function escHtml(s) {
    return (s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ---------------------------------------------------------------------------
// SMART panel
// ---------------------------------------------------------------------------
function showSmartPanel(btn) {
    var row = btn.closest('tr');
    var device = row.cells[0].textContent.trim();
    var section = btn.closest('[data-api-base]');
    var apiBase = section ? section.dataset.apiBase : 'api.cgi';
    var content = document.getElementById('smart-panel-content');
    content.innerHTML = '<div style="margin:8px 0;"><img src="/webman/3rdparty/drive_info/images/wait_triangle_blue_40p.gif" width="30" height="30" style="vertical-align:middle;margin-right:6px;"><span style="font-size:12px;">${_txt_loading}</span></div>';
    document.getElementById('smart-panel').classList.add('open');
    document.getElementById('smart-overlay').classList.add('open');

    var xhr = new XMLHttpRequest();
    xhr.open('GET', apiBase + '?action=get_smart&device=' + encodeURIComponent(device) + '&lang=' + encodeURIComponent(viewer_lang), true);
    xhr.timeout = 60000;
    xhr.onreadystatechange = function() {
        if (xhr.readyState !== 4) return;
        if (xhr.status === 200) {
            content.innerHTML = xhr.responseText;
        } else if (xhr.status !== 0) {
            content.innerHTML = '<p class="err">HTTP ' + xhr.status + '</p>';
        }
    };
    xhr.ontimeout = function() {
        content.innerHTML = '<p class="err">${_txt_smart_timeout}</p>';
    };
    xhr.onerror = function() {
        content.innerHTML = '<p class="err">${_txt_smart_failed}</p>';
    };
    xhr.send();
}

function closeSmartPanel() {
    document.getElementById('smart-panel').classList.remove('open');
    document.getElementById('smart-overlay').classList.remove('open');
}

fetchHAPassive();
fetchRemoteNAS();
</script>
JAVASCRIPT
