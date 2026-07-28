#!/bin/bash
#--------------------------------------------------------
# task_scheduler.sh - wrapper around SYNO.Core.TaskScheduler create/delete
#
# api.cgi runs as the non-root 'drive_info' package user, and
# SYNO.Core.TaskScheduler only succeeds when synowebapi is run with root/
# admin context. This script is called via sudo (see /etc/sudoers.d/drive_info)
# so it runs as root, then calls synowebapi directly. create's -s handling
# follows smart_info.sh's DSM7 (-s) vs DSM6 (no -s) pattern - delete does
# NOT (see DELETE_WEBAPI_FLAG below), since that pattern doesn't hold for it.
#
# Always creates/deletes a daily-at-midnight, owner=root task - that's the
# only schedule this package currently needs (Drive Info SMART Schedule).
#
# Usage:
#   task_scheduler.sh create <name> <script_cmd> <notify_enable> <notify_if_error> <notify_email>
#   task_scheduler.sh delete <id> <owner>
#   task_scheduler.sh list
#--------------------------------------------------------

set -u

SYNOWEBAPI="/usr/syno/bin/synowebapi"

# Get DSM major version - DSM 7 needs -s for create, DSM 6 must NOT have -s
# for create (this part is well-established/working on both versions).
dsm=$(/usr/syno/bin/synogetkeyvalue /etc.defaults/VERSION majorversion)
if [[ "$dsm" -ge 7 ]]; then
    WEBAPI_FLAG="-s"
else
    WEBAPI_FLAG=""
fi

# delete needs different handling per DSM version:
#   DSM 7: -s, version=2, tasks=[{"id":..,"real_owner":".."}] (JSON array)
#   DSM 6: no -s, version=1, task=<id> (bare id, not an array/object)
# version=2 without -s on DSM 6 errors 103 ("method does not exist" for that
# version); version=1 with the plural "tasks" param on DSM 6 returns
# success:true without actually deleting anything (silently ignored
# unrecognised param) - the singular "task" bare-id param is what DSM 6
# actually expects.
if [[ "$dsm" -ge 7 ]]; then
    DELETE_WEBAPI_FLAG="-s"
    DELETE_VERSION=2
else
    DELETE_WEBAPI_FLAG=""
    DELETE_VERSION=1
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
            name="\"$_name_json\"" owner="\"root\"" enable=true type="\"script\"" \
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

        if [[ "$dsm" -ge 7 ]]; then
            $SYNOWEBAPI $DELETE_WEBAPI_FLAG --exec api=SYNO.Core.TaskScheduler method=delete version=$DELETE_VERSION \
                tasks="[{\"id\":${_id},\"real_owner\":\"${_owner_json}\"}]"
        else
            $SYNOWEBAPI $DELETE_WEBAPI_FLAG --exec api=SYNO.Core.TaskScheduler method=delete version=$DELETE_VERSION \
                task=${_id}
        fi
        ;;
    list)
        # Read-only enumeration, used to reconcile our own tracked task_id
        # against what actually exists in Task Scheduler (e.g. after a
        # manual delete via the DSM GUI, or any delete/create mismatch).
        # WEBAPI_FLAG (not DELETE_WEBAPI_FLAG) is used here since list is a
        # plain read like create, not the special-cased delete - confirmed
        # working without -s on DSM 6 via direct testing; DSM 7's -s
        # requirement for this specific method is assumed from the create
        # pattern, not separately confirmed.
        $SYNOWEBAPI $WEBAPI_FLAG --exec api=SYNO.Core.TaskScheduler method=list version=1
        ;;
    *)
        echo '{"success":false,"error":"unknown action"}'
        exit 1
        ;;
esac
