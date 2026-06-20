#!/bin/bash

PKG_NAME="drive_info"
PKG_ROOT="/var/packages/${PKG_NAME}"
TARGET_DIR="${PKG_ROOT}/target"
SCRIPT="${TARGET_DIR}/ui/bin/drive_info.sh"
SUDOERS_FILE="/etc/sudoers.d/${PKG_NAME}"

# shellcheck source=ui/modules/get_text.sh
source "${TARGET_DIR}/ui/modules/get_text.sh"

echo "Content-Type: text/html; charset=utf-8"
echo ""

# Shared CSS
cat << 'STYLE'
<style>
body { font-family: Verdana, Arial, sans-serif; font-size: 13px; color: #333;
       margin: 16px; margin-right: 14px; background: transparent;
       overflow-y: auto; }
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
.err    { color: #c00; }
a { color: #0073c0; }
</style>
STYLE

# Check script exists
if [[ ! -f "$SCRIPT" ]]; then
    echo "<p class=\"err\">$(txt errors err_script_missing "drive_info.sh not found. Try reinstalling the package.")</p>"
    exit 0
fi

# Check sudo permission is granted (sudoers.d files aren't readable by
# the drive_info user, so ask sudo directly rather than grepping the file)
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
NOPERMS
    exit 0
fi


# Show spinner immediately, then run script and replace with results
loading=$(txt common loading "Loading...")
cat << SPINNER
<div id="loading">
  <img src="/webman/3rdparty/drive_info/images/wait_triangle_blue_40p.gif" alt="" width="40" height="40">
  <span>$loading</span>
  
</div>
<div id="result" style="display:none;"></div>
<script>
function showResult(html) {
    document.getElementById('loading').style.display = 'none';
    var r = document.getElementById('result');
    r.innerHTML = html;
    r.style.display = '';
}
</script>
SPINNER

# Flush the spinner to the browser immediately
# (CGI stdout is line-buffered; printing a large enough chunk forces it out)
dd if=/dev/zero bs=4096 count=1 2>/dev/null | tr '\0' ' '


# Run the script as root via sudo
STDERR_TMP=$(mktemp)
OUTPUT=$(sudo "${SCRIPT}" 2>"$STDERR_TMP")
EXIT_CODE=$?
STDERR_OUT=$(cat "$STDERR_TMP")
rm -f "$STDERR_TMP"


# Clear spinner and Loading drive information… from iframe
echo '<script>document.getElementById("loading").style.display="none";</script>'


# Check if sudo itself failed
if echo "$STDERR_OUT" | grep -qi "not in the sudoers\|sudoers file\|not allowed\|password is required"; then
    cat << SUDOFAIL
<h2 style="color:#c00;">$(txt errors err_sudofail_title "Permissions not configured correctly")</h2>
<p>$(txt errors err_sudofail_desc "The sudoers entry exists but sudo failed. Check the entry is correct:")</p>
<pre>cat $SUDOERS_FILE</pre>
<p>$(txt errors err_sudofail_must_contain "It should contain exactly:")</p>
<pre>drive_info ALL=(root) NOPASSWD: $SCRIPT</pre>
<p>$(txt errors err_see_details "See <a href=\"https://github.com/007revad/Synology_drive_info/blob/main/set_package_permissions.md\" target=\"_blank\">set_package_permissions.md</a> for full details.")</p>
SUDOFAIL
    exit 0
fi

if [[ $EXIT_CODE -ne 0 ]]; then
    echo "<p class=\"err\">drive_info.sh exited with code $EXIT_CODE.</p>"
    [[ -n "$STDERR_OUT" ]] && echo "<pre>$(echo "$STDERR_OUT" | sed 's/</\&lt;/g;s/>/\&gt;/g')</pre>"
    exit 0
fi

# Parse and render the plain-text table output as HTML
echo "<h2>$(txt common drive_information "Drive Information")</h2>"

in_table=0
headers=()
col_count=0

# Pre-scan: check whether the Location column (always index 2) has any
# non-empty value across the whole output, so the column can be hidden
# entirely if it's empty for every drive row.
HAS_LOCATION=0
scan_in_table=0
scan_headers=()
scan_col_starts=()
scan_col_count=0
while IFS= read -r line; do
    trimmed="${line#"${line%%[![:space:]]*}"}"  # ltrim

    if [[ "$trimmed" =~ ^-+$ ]]; then
        scan_in_table=1
        continue
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
        val="${val%"${val##*[![:space:]]}"}"  # trim trailing padding
        if [[ -n "$val" ]]; then
            HAS_LOCATION=1
            break
        fi
        continue
    fi

    if [[ $scan_in_table -eq 1 ]] && [[ ${#scan_headers[@]} -gt 0 ]] && [[ -z "$trimmed" ]]; then
        scan_in_table=0
        scan_headers=()
        continue
    fi
done <<< "$OUTPUT"

while IFS= read -r line; do
    trimmed="${line#"${line%%[![:space:]]*}"}"  # ltrim

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
        in_table=0
        headers=()
        continue
    fi

done <<< "$OUTPUT"

[[ $in_table -eq 1 ]] && echo "</tbody></table>"
