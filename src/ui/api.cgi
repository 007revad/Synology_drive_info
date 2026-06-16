#!/bin/bash

PKG_NAME="drive_info"
PKG_ROOT="/var/packages/${PKG_NAME}"
TARGET_DIR="${PKG_ROOT}/target"
SCRIPT="${TARGET_DIR}/bin/drive_info.sh"
SUDOERS_FILE="/etc/sudoers.d/${PKG_NAME}"

echo "Content-Type: application/json; charset=utf-8"
echo "Access-Control-Allow-Origin: *"
echo ""

# Check sudo permissions are configured
check_permissions() {
    # Check sudoers file exists and contains the right entry
    if [[ ! -f "$SUDOERS_FILE" ]]; then
        echo '{"success":false,"error":"no_sudoers"}'
        exit 0
    fi
    if ! grep -q "$SCRIPT" "$SUDOERS_FILE" 2>/dev/null; then
        echo '{"success":false,"error":"no_sudoers"}'
        exit 0
    fi
}

# Check script exists
if [[ ! -f "$SCRIPT" ]]; then
    echo '{"success":false,"error":"no_script"}'
    exit 0
fi

check_permissions

# Run drive_info.sh as root via sudo, capture stdout and stderr
STDERR_TMP=$(mktemp)
OUTPUT=$(sudo "${SCRIPT}" 2>"$STDERR_TMP")
EXIT_CODE=$?
STDERR_OUT=$(cat "$STDERR_TMP")
rm -f "$STDERR_TMP"

# Check if sudo itself failed (permissions not set correctly)
if echo "$STDERR_OUT" | grep -q "not in the sudoers\|sudoers file\|not allowed"; then
    echo '{"success":false,"error":"no_sudoers"}'
    exit 0
fi

if [[ $EXIT_CODE -ne 0 ]]; then
    ERR_JSON=$(python3 -c "import json,sys; print(json.dumps(sys.stdin.read().strip()))" <<< "$STDERR_OUT")
    echo "{\"success\":false,\"error\":\"script_failed\",\"detail\":${ERR_JSON}}"
    exit 0
fi

# Return output as JSON string
OUT_JSON=$(python3 -c "import json,sys; print(json.dumps(sys.stdin.read()))" <<< "$OUTPUT")
echo "{\"success\":true,\"output\":${OUT_JSON}}"
exit 0
