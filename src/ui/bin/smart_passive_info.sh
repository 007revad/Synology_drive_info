#!/usr/bin/env bash
#-----------------------------------------------------------------------
# smart_passive_info.sh
#
# Shows SMART info for a drive on the HA passive node. Unlike
# smart_info.sh (which reads smartctl directly - local devices only),
# this calls SYNO.Storage.CGI.Smart/get_health_info relayed through
# SYNO.SHA.Util/send_remote_webapi, since smartctl has no concept of a
# remote drive at all.
#
# Usage: smart_passive_info.sh --dev=/dev/sas1[,ger] [-i|--important]
#-----------------------------------------------------------------------

# Check script is running as root
if [[ $( whoami ) != "root" ]]; then
    echo -e "\nERROR This script must be run as sudo or root!\n"
    exit 1
fi

# Get DSM major version
dsm=$(/usr/syno/bin/synogetkeyvalue /etc.defaults/VERSION majorversion)

#-----------------------------------------------------------------------
# Argument parsing - mirrors smart_info.sh's --dev= splitting/validation
#-----------------------------------------------------------------------
all="no"
important="no"
if options="$(getopt -o ai -l dev:,all,increased -- "$@")"; then
    eval set -- "$options"
    while true; do
        case "${1,,}" in
            --dev)
                _lang=""
                _devarg="$2"
                if [[ "$_devarg" == *","* ]]; then
                    _lang="${_devarg#*,}"
                    _devarg="${_devarg%%,*}"
                fi

                if [[ $_lang =~ ^(chs|cht|csy|dan|enu|fre|ger|hun|ita|jpn|krn|nld|nor|plk|ptb|ptg|rus|spn|sve|tha|trk)$ ]]; then
                    gui_lang="$_lang"
                else
                    gui_lang="$(synogetkeyvalue /etc/synoinfo.conf maillang)"
                fi

                case "$(basename -- "$_devarg")" in
                    sata*|sas*)
                        if [[ $_devarg =~ (sas|sata)[0-9][0-9]?[0-9]?$ ]]; then
                            device="$_devarg"
                        fi
                    ;;
                    sd*)
                        if [[ $_devarg =~ sd[a-z][a-z]?$ ]]; then
                            device="$_devarg"
                        fi
                    ;;
                    nvme*)
                        if [[ $_devarg =~ nvme[0-9][0-9]?n[0-9][0-9]?$ ]]; then
                            device="$_devarg"
                        fi
                    ;;
                esac
                shift
                ;;
            -a|--all)           # Show all SMART attributes
                all=yes
                ;;
            -i|--increased)     # Only display increased attributes
                increased=yes
                ;;
            --)
                shift
                break
            ;;
        esac
        shift
    done
fi

if [[ -z "$device" ]]; then
    echo -e "\nERROR --dev must be a valid passive-node device path (e.g. /dev/sas1, /dev/sata1)\n"
    exit 1
fi

# Load translated strings if running from within the installed package.
# modules/get_text.sh and the texts/ folder won't exist if this script
# is run standalone (e.g. downloaded directly from GitHub), in which
# case fall back to printing the English defaults below.
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
get_text_module="$(dirname "${script_dir}")/modules/get_text.sh"
if [[ -f "${get_text_module}" ]]; then
    # shellcheck source=/dev/null
    source "${get_text_module}" "$gui_lang"
else
    txt() { echo "${3}"; }  # txt SECTION KEY DEFAULT -> just print DEFAULT
fi

#-----------------------------------------------------------------------
# Color markers - always GUI/marker mode here, since this is only ever
# invoked from api.cgi via sudo, never interactively.
#-----------------------------------------------------------------------
LiteRed="red::"
LiteGreen="green::"
Yellow="blue::"
Off=""

#-----------------------------------------------------------------------
# Fetch SMART data via the relay
#-----------------------------------------------------------------------
_device_json_arg="{\\\"device\\\":\\\"${device}\\\"}"
if [[ "$dsm" -le "6" ]]; then
    _smart_result=$(synowebapi --exec api=SYNO.SHA.Util method=send_remote_webapi version=1 \
        remote_api="\"SYNO.Storage.CGI.Smart\"" remote_method="\"get_health_info\"" remote_version=1 \
        remote_params="$_device_json_arg" 2>/dev/null)
else
    _smart_result=$(synowebapi -s --exec api=SYNO.SHA.Util method=send_remote_webapi version=1 \
        remote_api="\"SYNO.Storage.CGI.Smart\"" remote_method="\"get_health_info\"" remote_version=1 \
        remote_params="$_device_json_arg" 2>/dev/null)
fi

_success=$(echo "$_smart_result" | jq -r '.success // false' 2>/dev/null)
if [[ "$_success" != "true" ]]; then
    echo -e "${LiteRed}ERROR: Could not retrieve SMART data for $device from passive node${Off}"
    exit 1
fi

#---------------------------------------------------------------------------
# Overall health result - hardcoded English, matching smart_info.sh
# (smartctl output is English-only, so surrounding labels stay English too)
#---------------------------------------------------------------------------
_smart_status=$(echo "$_smart_result" | jq -r '.data.healthInfo.overview.smart // "unknown"')
if [[ "$_smart_status" == "normal" ]]; then
    echo -e "SMART overall-health self-assessment test result: ${LiteGreen}PASSED${Off}"
else
    echo -e "SMART overall-health self-assessment test result: ${LiteRed}${_smart_status}${Off}"
fi

#-----------------------------------------------------------------------
# Error Counter Log - overview.smart_fail
#-----------------------------------------------------------------------
_fail_count=$(echo "$_smart_result" | jq -r '.data.healthInfo.overview.smart_fail | length')
if [[ "$_fail_count" -gt 0 ]]; then
    echo -e "SMART Error Counter Log:         ${LiteRed}${_fail_count}${Off}"
else
    echo -e "SMART Error Counter Log:         ${LiteGreen}No Errors Logged${Off}"
fi

echo ""

#-----------------------------------------------------------------------
# Attribute table
#-----------------------------------------------------------------------
important_ids="1 5 7 9 10 187 188 190 194 195 197 198 199 200 252"

if [[ "$all" != "yes" ]]; then
    # Important mode: no header (parser auto-generates one). Row shape:
    # "<id> blue::<name-padded> <raw>" - matches short_attibutes' pattern,
    # 28-char name padding for plain-text/email readability.
    echo "$_smart_result" | jq -r --arg ids "$important_ids" '
        (.data.healthInfo.smartInfo // [])[] |
        select(($ids | split(" ") | index(.id)) != null) |
        "\(.id)\t\(.name)\t\(.raw)\t\(.status)"
    ' | while IFS=$'\t' read -r id name raw status; do
        raw_out="$raw"
        [[ "$status" != "OK" ]] && raw_out="${LiteRed}${raw}${Off}"
        printf "%-4s${Yellow}%-28s${Off} %s\n" "$id" "$name" "$raw_out"
    done
else
    # Full mode: header must literally contain ATTRIBUTE_NAME and FLAGS
    # for the parser to select 8-column mode. No FLAGS field exists in
    # this JSON, so it's a fixed placeholder. Never colorized - matches
    # the local view's plain-text full table.
    printf "%-4s %-32s %-8s %6s %6s %7s %6s %s\n" \
        "ID#" "ATTRIBUTE_NAME" "FLAGS" "VALUE" "WORST" "THRESH" "FAIL" "RAW_VALUE"
    echo "$_smart_result" | jq -r '
        (.data.healthInfo.smartInfo // [])[] |
        "\(.id)\t\(.name)\t\(.current)\t\(.worst)\t\(.threshold)\t\(.status)\t\(.raw)"
    ' | while IFS=$'\t' read -r id name current worst threshold status raw; do
        fail="-"
        [[ "$status" != "OK" ]] && fail="$status"
        printf "%-4s %-32s %-8s %6s %6s %7s %6s %s\n" "$id" "$name" "-" "$current" "$worst" "$threshold" "$fail" "$raw"
    done
fi

