#!/bin/sh
# shebang needs to be sh as SRM does not have bash
#
# srm_package_source.sh - lets an SRM package add 007revad's package source
# to Package Center and keep its icons working.
#
#   install [yes|no]
#            add this package's marker, add the feed, and enable the Community
#            tab only if yes. With no argument the earlier choice is kept
#            (an upgrade does not show the install wizard); the default is no
#   remove   remove this package's marker; when no marker is left, remove the
#            feed and undo the Community tab patch
#   release  remove this package's marker only; the feed and patch stay
#   daemon   check the feed and the Community tab patch once (an SRM update
#            reboots and restarts the package), then loop filling the
#            thumbnail cache. Started by start-stop-status
#   fill     one thumbnail pass, then exit
#   status   print what is in place
#
# Several packages can ship this same script. Each one leaves a marker file in
# MARKER_DIR, and the feed and patch only go away with the last marker.

PKG_NAME="drive_info"
case "$0" in
    /var/packages/*/target/*)
        PKG_NAME="${0#/var/packages/}"
        PKG_NAME="${PKG_NAME%%/*}"
        ;;
esac

# Get OS name
os_name=$(/usr/syno/bin/synogetkeyvalue /etc.defaults/synoinfo.conf os_name)
# Only needed for SRM
if [ "$os_name" != SRM ]; then
    exit 0
fi

# A package script's PATH can differ from a login shell's, so look for the
# tools in the usual places instead of relying on PATH alone.
find_tool() {
    t=$(command -v "$1" 2>/dev/null)
    if [ -n "$t" ] && [ -x "$t" ]; then echo "$t"; return 0; fi
    for d in /bin /usr/bin /usr/syno/bin /usr/local/bin /opt/bin; do
        if [ -x "$d/$1" ]; then echo "$d/$1"; return 0; fi
    done
    return 1
}
JQ=$(find_tool jq)
CURL=$(find_tool curl)

FEED_URL="https://spkrepo.007daver.workers.dev/?ref=srm"
FEED_NAME="007revad"

FEEDS_FILE="/usr/syno/etc/packages/feeds"
JS_FILE="/usr/syno/synoman/webman/modules/PkgManApp/PkgManApp.js"
MARKER_DIR="/usr/syno/etc/packages/007revad_feed_users"

# Package Center's list and icon cache. /tmp/pkglist.tmp is a symlink to a USB
# drive on at least one router, so check it exists before writing into it.
CACHE_ROOT="/tmp/pkglist.tmp"
LIST_FILE="${CACHE_ROOT}/otherserver.enu"
ICON_DIR="${CACHE_ROOT}/icon/AVAIL/OTHER"

LOG_FILE="/var/packages/${PKG_NAME}/etc/source_helper.log"
FAILED_FILE="/tmp/${PKG_NAME}_source_failed.list"
INTERVAL=5

WARNED=""

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE" 2>/dev/null
}

# Log a problem once per daemon run, not once a minute
warn_once() {
    case " $WARNED " in
        *" $1 "*) return 0 ;;
    esac
    WARNED="$WARNED $1"
    log "$2"
}

need_root() {
    if [ "$(id -u)" != "0" ]; then
        log "ERROR: $1 needs root (running as $(id -un))"
        echo "ERROR: must run as root" >&2
        exit 1
    fi
}

#--------------------------------------------------------------------
# Feed file: a JSON array, e.g. [{"feed":"https://...","name":"007revad"}]
# Entries from other sources are never touched.
#--------------------------------------------------------------------
add_feed() {
    [ -n "$JQ" ] || { warn_once jq "jq not found (PATH=$PATH) - feed not added"; return 1; }
    tmp="/tmp/${PKG_NAME}_feeds.$$"

    if [ -s "$FEEDS_FILE" ]; then
        kind=$("$JQ" -r 'type' "$FEEDS_FILE" 2>/dev/null)
        if [ "$kind" != "array" ]; then
            warn_once feedfmt "ERROR: $FEEDS_FILE is not a JSON array - left alone"
            return 1
        fi
        have=$("$JQ" -r --arg u "$FEED_URL" 'map(select(.feed == $u)) | length' "$FEEDS_FILE" 2>/dev/null)
        case "$have" in
            0) ;;
            [0-9]*) return 0 ;;
            *) warn_once feedfmt "ERROR: could not read entries in $FEEDS_FILE - left alone"; return 1 ;;
        esac
        "$JQ" -c --arg u "$FEED_URL" --arg n "$FEED_NAME" '. + [{"feed": $u, "name": $n}]' \
            "$FEEDS_FILE" > "$tmp" 2>/dev/null
    else
        "$JQ" -n -c --arg u "$FEED_URL" --arg n "$FEED_NAME" '[{"feed": $u, "name": $n}]' > "$tmp" 2>/dev/null
    fi

    if [ -s "$tmp" ] && [ "$("$JQ" -r 'type' "$tmp" 2>/dev/null)" = "array" ]; then
        # cat > keeps the existing file's owner and permissions
        cat "$tmp" > "$FEEDS_FILE" && log "Added feed $FEED_URL"
        rm -f "$tmp"
        return 0
    fi
    rm -f "$tmp"
    warn_once feedwrite "ERROR: could not build the new feeds file"
    return 1
}

remove_feed() {
    [ -s "$FEEDS_FILE" ] || return 0
    [ -n "$JQ" ] || { log "jq not found - feed not removed"; return 1; }
    [ "$("$JQ" -r 'type' "$FEEDS_FILE" 2>/dev/null)" = "array" ] || return 1
    tmp="/tmp/${PKG_NAME}_feeds.$$"
    "$JQ" -c --arg u "$FEED_URL" 'map(select(.feed != $u))' "$FEEDS_FILE" > "$tmp" 2>/dev/null
    [ -s "$tmp" ] || { rm -f "$tmp"; return 1; }
    if [ "$("$JQ" -r 'length' "$tmp" 2>/dev/null)" = "0" ]; then
        # the file did not exist before the first package added it
        rm -f "$FEEDS_FILE"
    else
        cat "$tmp" > "$FEEDS_FILE"
    fi
    rm -f "$tmp"
    log "Removed feed $FEED_URL"
}

#--------------------------------------------------------------------
# Community tab: SRM's PkgManApp.js only builds the left-hand list entries
# named in var d=[...]. Adding "community" makes the tab exist.
# Browsers need a sign-out/sign-in (and sometimes Ctrl+F5) to see a change.
#--------------------------------------------------------------------
JS_OLD='var d=["installed","update","all","beta"]'
JS_NEW='var d=["installed","update","all","beta","community"]'

# Each marker file holds "community=yes" or "community=no". The Community tab
# patch is wanted while any installed package that uses the feed said yes.
community_wanted() {
    for m in "$MARKER_DIR"/*; do
        [ -f "$m" ] || continue
        n=$(basename "$m")
        [ -d "/var/packages/${n}" ] || continue
        grep -qx 'community=yes' "$m" 2>/dev/null && return 0
    done
    return 1
}

reconcile_patch() {
    if community_wanted; then
        patch_js
    else
        unpatch_js
    fi
}

patch_js() {
    if [ ! -f "$JS_FILE" ]; then
        warn_once jsmissing "ERROR: $JS_FILE not found"
        return 1
    fi
    grep -qF "$JS_NEW" "$JS_FILE" && return 0
    if ! grep -qF "$JS_OLD" "$JS_FILE"; then
        warn_once jspattern "WARNING: expected text not found in PkgManApp.js - SRM may have changed it"
        return 1
    fi
    [ -e "${JS_FILE}.orig" ] || cp -p "$JS_FILE" "${JS_FILE}.orig"
    tmp="/tmp/${PKG_NAME}_js.$$"
    sed 's/var d=\["installed","update","all","beta"\]/var d=["installed","update","all","beta","community"]/' \
        "$JS_FILE" > "$tmp"
    if [ -s "$tmp" ] && grep -qF "$JS_NEW" "$tmp"; then
        cat "$tmp" > "$JS_FILE" && log "Patched PkgManApp.js (Community tab)"
        rm -f "$tmp"
        return 0
    fi
    rm -f "$tmp"
    warn_once jspatch "ERROR: patching PkgManApp.js failed"
    return 1
}

unpatch_js() {
    [ -f "$JS_FILE" ] || return 0
    grep -qF "$JS_NEW" "$JS_FILE" || return 0
    tmp="/tmp/${PKG_NAME}_js.$$"
    sed 's/var d=\["installed","update","all","beta","community"\]/var d=["installed","update","all","beta"]/' \
        "$JS_FILE" > "$tmp"
    if [ -s "$tmp" ] && grep -qF "$JS_OLD" "$tmp"; then
        cat "$tmp" > "$JS_FILE" && log "Reverted PkgManApp.js patch"
    fi
    rm -f "$tmp"
}

#--------------------------------------------------------------------
# Thumbnails. Package Center's own icon fetch rejects every community icon
# ("Failed to validate image uri"), so put the files where it looks:
#   <cache>/icon/AVAIL/OTHER/<package>/<version>/thumb_72.png  (tile)
#                                                 thumb_256.png (detail page)
# The package and version come from otherserver.enu, the list Package Center
# built from the feed, so the folder always matches what it asks for.
#--------------------------------------------------------------------
fetch_icon() {
    url="$1"
    dest="$2"
    case "$url" in
        https://*) ;;
        *) return 1 ;;
    esac
    tmp="${dest}.part"
    if "$CURL" -fsSL --max-time 30 -o "$tmp" "$url" 2>/dev/null \
        && [ -s "$tmp" ] \
        && [ "$(dd if="$tmp" bs=1 skip=1 count=3 2>/dev/null)" = "PNG" ]; then
        chmod 644 "$tmp"
        mv "$tmp" "$dest" && return 0
    fi
    rm -f "$tmp"
    return 1
}

fill_icons() {
    retry="${1:-0}"
    [ -s "$LIST_FILE" ] || return 0
    [ -d "${CACHE_ROOT}/" ] || return 0
    [ -n "$JQ" ] || return 0
    [ -n "$CURL" ] || return 0
    [ "$retry" = "1" ] && : > "$FAILED_FILE"

    "$JQ" -r '.[] | select(.package and .version)
           | .package + " " + .version + " " + (.thumbnail[0] // "-") + " " + (.thumbnail[1] // .thumbnail[0] // "-")' \
        "$LIST_FILE" 2>/dev/null | while read -r pkg ver u72 u256; do

        # These become path components, so keep them boring
        case "$pkg" in ""|.*|*[!A-Za-z0-9._+-]*) continue ;; esac
        case "$ver" in ""|.*|*[!A-Za-z0-9._+-]*) continue ;; esac

        d="${ICON_DIR}/${pkg}/${ver}"
        key="${pkg}/${ver}"
        if [ -s "$d/thumb_72.png" ] && [ -s "$d/thumb_256.png" ]; then
            continue
        fi
        if [ -f "$FAILED_FILE" ] && grep -qxF "$key" "$FAILED_FILE"; then
            continue
        fi
        if [ "$u72" = "-" ]; then
            echo "$key" >> "$FAILED_FILE"
            log "icons: $key has no thumbnail URL"
            continue
        fi
        mkdir -p "$d" || { echo "$key" >> "$FAILED_FILE"; log "icons: cannot create $d"; continue; }

        bad=0
        if [ ! -s "$d/thumb_72.png" ]; then
            fetch_icon "$u72" "$d/thumb_72.png" || bad=1
        fi
        if [ ! -s "$d/thumb_256.png" ]; then
            if [ "$u256" = "$u72" ] && [ -s "$d/thumb_72.png" ]; then
                # feed lists one thumbnail only: use it for both views
                cp "$d/thumb_72.png" "$d/thumb_256.png"
            else
                fetch_icon "$u256" "$d/thumb_256.png" || bad=1
            fi
        fi

        if [ "$bad" = "1" ]; then
            echo "$key" >> "$FAILED_FILE"
            log "icons: download failed for $key"
        else
            log "icons: $key done"
        fi
    done
}

#--------------------------------------------------------------------
# Actions
#--------------------------------------------------------------------
do_install() {
    need_root install
    case "$1" in
        yes|true)  choice=yes ;;
        no|false)  choice=no ;;
        *)
            # No answer (e.g. an upgrade): keep the earlier choice, default no
            choice=no
            grep -qx 'community=yes' "${MARKER_DIR}/${PKG_NAME}" 2>/dev/null && choice=yes
            ;;
    esac
    mkdir -p "$MARKER_DIR" && echo "community=${choice}" > "${MARKER_DIR}/${PKG_NAME}"
    add_feed
    reconcile_patch
    log "install: done for $PKG_NAME (community tab: ${choice})"
    return 0
}

do_remove() {
    need_root remove
    rm -f "${MARKER_DIR}/${PKG_NAME}"

    # Forget markers left by packages that no longer exist
    for m in "$MARKER_DIR"/*; do
        [ -e "$m" ] || continue
        n=$(basename "$m")
        [ -d "/var/packages/${n}" ] || rm -f "$m"
    done

    left=$(ls "$MARKER_DIR" 2>/dev/null | wc -l)
    if [ "$left" -eq 0 ]; then
        remove_feed
        unpatch_js
        rmdir "$MARKER_DIR" 2>/dev/null
        rm -f "$FAILED_FILE"
        log "remove: last package gone - feed and patch removed"
    else
        reconcile_patch
        log "remove: $left other package(s) still use the feed - left in place"
    fi
    return 0
}

do_release() {
    need_root release
    rm -f "${MARKER_DIR}/${PKG_NAME}"
    rm -f "$FAILED_FILE"
    log "release: marker removed - feed and patch left in place"
    return 0
}

do_daemon() {
    need_root daemon
    log "daemon: started (pid $$)"

    # An SRM update reboots the router and starts this package again, so the
    # feed and the Community tab patch only need checking once, here.
    add_feed >/dev/null 2>&1
    reconcile_patch >/dev/null 2>&1

    i=0
    while :; do
        # package removed without stop being called
        [ -d "/var/packages/${PKG_NAME}/target" ] || { log "daemon: package gone - exiting"; exit 0; }

        retry=0
        [ $((i % 10)) -eq 0 ] && retry=1
        fill_icons "$retry"

        # keep the log small
        if [ $((i % 60)) -eq 59 ] && [ -f "$LOG_FILE" ] && [ "$(wc -c < "$LOG_FILE")" -gt 100000 ]; then
            tail -n 200 "$LOG_FILE" > "/tmp/${PKG_NAME}_log.$$" && cat "/tmp/${PKG_NAME}_log.$$" > "$LOG_FILE"
            rm -f "/tmp/${PKG_NAME}_log.$$"
        fi

        i=$((i + 1))
        sleep "$INTERVAL"
    done
}

do_status() {
    for m in "$MARKER_DIR"/*; do
        [ -f "$m" ] && echo "marker:   $(basename "$m") ($(cat "$m"))"
    done
    if community_wanted; then echo "community tab wanted: yes"; else echo "community tab wanted: no"; fi
    if [ -f "$FEEDS_FILE" ]; then echo "feeds:    $(cat "$FEEDS_FILE")"; else echo "feeds:    (no file)"; fi
    if grep -qF "$JS_NEW" "$JS_FILE" 2>/dev/null; then echo "js patch: applied"; else echo "js patch: NOT applied"; fi
    if [ -f "$LIST_FILE" ]; then echo "list:     $LIST_FILE present"; else echo "list:     $LIST_FILE missing"; fi
    for d in "$ICON_DIR"/*/*; do
        [ -d "$d" ] || continue
        echo "icons:    ${d#${ICON_DIR}/}: $(ls "$d" 2>/dev/null | tr '\n' ' ')"
    done
    return 0
}

case "$1" in
    install) do_install "$2" ;;
    remove)  do_remove ;;
    release) do_release ;;
    daemon)  do_daemon ;;
    fill)    need_root fill; fill_icons 1 ;;
    status)  do_status ;;
    *)
        echo "Usage: $0 {install [yes|no]|remove|release|daemon|fill|status}" >&2
        exit 1
        ;;
esac
exit 0
