#!/bin/bash
#--------------------------------------------------------
# task_scheduler.sh - wrapper around SYNO.Core.TaskScheduler create/delete
#
# api.cgi runs as the non-root 'drive_info' package user, and
# SYNO.Core.TaskScheduler only succeeds when synowebapi is run with root/
# admin context. This script is called via sudo (see /etc/sudoers.d/drive_info)
# so it runs as root, then calls synowebapi directly - same pattern as
# smart_info.sh's DSM7 (-s) vs DSM6 (no -s) branch.
#
# Always creates/deletes a daily-at-midnight, owner=root task - that's the
# only schedule this package currently needs (Drive Info SMART Schedule).
#
# Usage:
#   task_scheduler.sh create <name> <script_cmd> <notify_enable> <notify_if_error> <notify_email>
#   task_scheduler.sh delete <id> <owner>
#--------------------------------------------------------

set -u

SYNOWEBAPI="/usr/syno/bin/synowebapi"

# Get DSM major version - DSM 7 needs -s, DSM 6 must NOT have -s
dsm=$(/usr/syno/bin/synogetkeyvalue /etc.defaults/VERSION majorversion)
if [[ "$dsm" -ge 7 ]]; then
    WEBAPI_FLAG="-s"
else
    WEBAPI_FLAG=""
fi

# Escape backslash and double-quote for safe embedding in a JSON string
json_escape(){ 
    local s="$1"
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    printf '%s' "$s"
}

_action="${1:-}"

case "$_action" in
    create)
        _name="${2:-}"
        _script_cmd="${3:-}"
        _notify_enable="${4:-false}"
        _notify_if_error="${5:-false}"
        _notify_email="${6:-}"

        if [[ -z "$_name" || -z "$_script_cmd" ]]; then
            echo '{"success":false,"error":"missing required args"}'
            exit 1
        fi

        _name_json=$(json_escape "$_name")
        _script_json=$(json_escape "$_script_cmd")
        _email_json=$(json_escape "$_notify_email")

        _today=$(date +%Y/%-m/%-d)

        $SYNOWEBAPI $WEBAPI_FLAG --exec api=SYNO.Core.TaskScheduler method=create version=1 \
            name="$_name_json" owner="root" enable=true type="script" \
            extra="{\"script\":\"${_script_json}\",\"notify_enable\":${_notify_enable},\"notify_if_error\":${_notify_if_error},\"notify_mail\":\"${_email_json}\"}" \
            schedule="{\"date\":\"${_today}\",\"date_type\":0,\"hour\":0,\"minute\":0,\"repeat_date\":0,\"repeat_hour\":0,\"week_day\":\"0,1,2,3,4,5,6\"}"
        ;;
    delete)
        _id="${2:-}"
        _owner="${3:-root}"

        if [[ -z "$_id" ]] || [[ ! "$_id" =~ ^[0-9]+$ ]]; then
            echo '{"success":false,"error":"missing or invalid task id"}'
            exit 1
        fi

        _owner_json=$(json_escape "$_owner")

        $SYNOWEBAPI $WEBAPI_FLAG --exec api=SYNO.Core.TaskScheduler method=delete version=2 \
            tasks="[{\"id\":${_id},\"real_owner\":\"${_owner_json}\"}]"
        ;;
    *)
        echo '{"success":false,"error":"unknown action"}'
        exit 1
        ;;
esac
