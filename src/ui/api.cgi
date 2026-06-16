#!/bin/bash

PKG_NAME="drive_info"
PKG_ROOT="/var/packages/${PKG_NAME}"
TARGET_DIR="${PKG_ROOT}/target"
SCRIPT="${TARGET_DIR}/ui/bin/drive_info.sh"
SUDOERS_FILE="/etc/sudoers.d/${PKG_NAME}"

echo "Content-Type: text/html; charset=utf-8"
echo ""

# Shared CSS
cat << 'STYLE'
<style>
body { font-family: Arial, sans-serif; font-size: 13px; color: #333;
       margin: 16px; margin-right: 14px; background: transparent;
       overflow-y: auto; }
h2   { margin-top: 0; font-size: 15px; color: #333; }
pre  { background: #f4f4f4; border: 1px solid #ddd; border-radius: 4px;
       padding: 12px; font-size: 12px; line-height: 1.6;
       white-space: pre-wrap; word-break: break-all;
       box-sizing: border-box; max-width: 100%; }
table { border-collapse: collapse; width: 100%;
        box-sizing: border-box; table-layout: fixed;
        font-family: Arial, sans-serif; font-size: 12px; }
col.id     { width: 70px; }
col.num    { width: 160px; }
col.model  { width: 220px; }
col.serial { width: auto; }
th { text-align: left; padding: 5px 14px 5px 5px;
     border-bottom: 2px solid #ccc; color: #555;
     font-family: Arial, sans-serif; font-size: 12px; }
td { padding: 5px 14px 5px 5px; border-bottom: 1px solid #eee; }
.num    { color: #0073c0; font-weight: bold; }
.serial { color: #b5800a; }
.err    { color: #c00; }
a { color: #0073c0; }
</style>
STYLE

# Check script exists
if [[ ! -f "$SCRIPT" ]]; then
    echo '<p class="err">drive_info.sh not found. Try reinstalling the package.</p>'
    exit 0
fi

# Check sudo permission is granted (sudoers.d files aren't readable by
# the drive_info user, so ask sudo directly rather than grepping the file)
if ! sudo -n -l "$SCRIPT" >/dev/null 2>&1; then
    cat << NOPERMS
<h2 style="color:#c00;">Permissions not configured</h2>
<p>This package needs elevated permissions to read drive information.</p>
<p>Connect to your NAS via SSH and run:</p>
<pre>sudo -i
echo "drive_info ALL=(ALL) NOPASSWD: $SCRIPT" \\
    &gt; $SUDOERS_FILE
chmod 0440 $SUDOERS_FILE</pre>
<p>Then close and reopen this window.</p>
<p>See <a href="https://github.com/007revad/Synology_drive_info/blob/main/set_package_permissions.md"
   target="_blank">set_package_permissions.md</a> for full details.</p>
NOPERMS
    exit 0
fi

# Run the script as root via sudo
STDERR_TMP=$(mktemp)
OUTPUT=$(sudo "${SCRIPT}" 2>"$STDERR_TMP")
EXIT_CODE=$?
STDERR_OUT=$(cat "$STDERR_TMP")
rm -f "$STDERR_TMP"

# Check if sudo itself failed
if echo "$STDERR_OUT" | grep -qi "not in the sudoers\|sudoers file\|not allowed\|password is required"; then
    cat << SUDOFAIL
<h2 style="color:#c00;">Permissions not configured correctly</h2>
<p>The sudoers entry exists but sudo failed. Check the entry is correct:</p>
<pre>cat $SUDOERS_FILE</pre>
<p>It should contain exactly:</p>
<pre>drive_info ALL=(root) NOPASSWD: $SCRIPT</pre>
<p>See <a href="https://github.com/007revad/Synology_drive_info/blob/main/set_package_permissions.md"
   target="_blank">set_package_permissions.md</a> for full details.</p>
SUDOFAIL
    exit 0
fi

if [[ $EXIT_CODE -ne 0 ]]; then
    echo "<p class=\"err\">drive_info.sh exited with code $EXIT_CODE.</p>"
    [[ -n "$STDERR_OUT" ]] && echo "<pre>$(echo "$STDERR_OUT" | sed 's/</\&lt;/g;s/>/\&gt;/g')</pre>"
    exit 0
fi

# Parse and render the plain-text table output as HTML
echo "<h2>Drive Information</h2>"

in_table=0
headers=()
col_count=0

while IFS= read -r line; do
    trimmed="${line#"${line%%[![:space:]]*}"}"  # ltrim

    # Separator line
    if [[ "$trimmed" =~ ^-+$ ]]; then
        if [[ $in_table -eq 0 ]]; then
            in_table=1
            echo '<table><colgroup><col class="id"><col class="num"><col class="model"><col class="serial"></colgroup>'
        fi
        continue
    fi

    if [[ $in_table -eq 1 ]] && [[ ${#headers[@]} -eq 0 ]] && [[ -n "$trimmed" ]]; then
        # Header row — split on 2+ spaces
        IFS=$'\n' read -r -d '' -a headers <<< "$(echo "$trimmed" | grep -oP '\S.*?(?=  |\s*$)')" || true
        col_count=${#headers[@]}
        echo "<thead><tr>"
        for h in "${headers[@]}"; do
            echo "<th>$(echo "$h" | sed 's/</\&lt;/g;s/>/\&gt;/g')</th>"
        done
        echo "</tr></thead><tbody>"
        continue
    fi

    if [[ $in_table -eq 1 ]] && [[ ${#headers[@]} -gt 0 ]] && [[ -n "$trimmed" ]]; then
        # Data row
        IFS=$'\n' read -r -d '' -a cells <<< "$(echo "$trimmed" | grep -oP '\S.*?(?=  |\s*$)')" || true
        echo "<tr>"
        for (( c=0; c<col_count; c++ )); do
            val="${cells[$c]:-}"
            val="$(echo "$val" | sed 's/</\&lt;/g;s/>/\&gt;/g')"
            if [[ $c -eq 1 ]]; then
                echo "<td class=\"num\">$val</td>"
            elif [[ $c -eq 3 ]]; then
                echo "<td class=\"serial\">$val</td>"
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
        in_table=0
        headers=()
        continue
    fi

done <<< "$OUTPUT"

[[ $in_table -eq 1 ]] && echo "</tbody></table>"
