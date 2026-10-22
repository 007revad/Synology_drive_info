#!/bin/sh
# shebang needs to be sh as SRM does not have bash
#
# Uninstall wizard for the SRM package. Asks whether to also remove the
# 007revad package source (feed + Community tab). Only asks when no other
# package that uses the package source is installed; otherwise it shows
# nothing and the package source is left for the other package(s).

PKG_NAME="${SYNOPKG_PKGNAME:-drive_info}"
MARKER_DIR="/usr/syno/etc/packages/007revad_feed_users"

others=0
for m in "$MARKER_DIR"/*; do
    [ -e "$m" ] || continue
    n=$(basename "$m")
    [ "$n" = "$PKG_NAME" ] && continue
    [ -d "/var/packages/$n" ] && others=$((others + 1))
done

if [ "$others" -gt 0 ]; then
    json='[]'
else
    json=$(cat <<'JSON'
[
    {
        "step_title": "Uninstall Drive Info",
        "items": [
            {
                "type": "multiselect",
                "desc": "Drive Info added the 007revad package source to Package Center. It is what lets you reinstall Drive Info, and install other 007revad packages, from the Community tab.",
                "subitems": [
                    {
                        "key": "pkgwizard_remove_package_source",
                        "desc": "Also remove the 007revad package source and the Community tab - off by default",
                        "defaultValue": false
                    }
                ]
            },
            {
                "desc": "Leave this unchecked to keep the package source, so you can reinstall Drive Info from Package Center."
            },
            {
                "desc": "<strong style='color:red'>Note:</strong> with no 007revad package installed, nothing keeps the Community tab in place or shows the package icons, and an SRM update can remove the tab."
            }
        ]
    }
]
JSON
)
fi

if [ -n "${SYNOPKG_TEMP_LOGFILE:-}" ]; then
    echo "$json" | tee "$SYNOPKG_TEMP_LOGFILE"
else
    echo "$json"
fi

exit 0
