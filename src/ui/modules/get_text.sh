#!/usr/bin/env bash
#--------------------------------------------------------
# Resolve translated UI/notification strings for the
# drive_info package, based on the DSM GUI language.
#
# Looks for a texts/<lang>/strings file under ../texts
# relative to this module's own location, falling back to
# enu if the detected language has no strings file.
#
# Defines:
#   txt SECTION KEY DEFAULT
#     Looks up SECTION/KEY in the resolved strings file (read once
#     into memory). Prints DEFAULT if the strings
#     file is missing, the lookup fails, or the value is
#     empty.
#
# Github: https://github.com/007revad/Synology_drive_info
#---------------------------------------------------------

_get_text_module_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
_get_text_ui_dir="$(dirname "${_get_text_module_dir}")"


# Check if 1st argument is a DSM language code
if [[ $1 =~ chs|cht|csy|dan|enu|fre|ger|hun|ita|jpn|krn|nld|nor|plk|ptb|ptg|rus|spn|sve|tha|trk ]]; then
    gui_lang="$1"
else
    gui_lang="$(get_key_value /etc/synoinfo.conf maillang 2>/dev/null)"
fi

strings_file="${_get_text_ui_dir}/texts/${gui_lang}/strings"
[[ -f "${strings_file}" ]] || strings_file="${_get_text_ui_dir}/texts/enu/strings"

# Read the whole strings file into memory once.
# Calling get_section_key_value for every string starts a new process each
# time, which takes about 0.4 seconds per string on SRM (80+ strings).
declare -A _txt_cache
_txt_load(){
    local line section="" key value
    [[ -f "${strings_file}" ]] || return
    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line%$'\r'}"
        if [[ "$line" =~ ^[[:space:]]*\[([^]]+)\][[:space:]]*$ ]]; then
            section="${BASH_REMATCH[1]}"
        elif [[ "$line" == *=* ]]; then
            key="${line%%=*}"
            value="${line#*=}"
            # Trim spaces and tabs
            key="${key#"${key%%[![:space:]]*}"}"
            key="${key%"${key##*[![:space:]]}"}"
            value="${value#"${value%%[![:space:]]*}"}"
            value="${value%"${value##*[![:space:]]}"}"
            [[ -z "$key" || "$key" == [#\;]* ]] && continue
            # Remove the outer double quotes (the value may contain other quotes)
            if [[ "$value" == \"*\" ]]; then
                value="${value#\"}"
                value="${value%\"}"
            fi
            _txt_cache["${section}|${key}"]="$value"
        fi
    done < "${strings_file}"
}
_txt_load

txt(){ 
    local section="$1" key="$2" default="$3" value=""
    value="${_txt_cache["${section}|${key}"]-}"
    [[ -z "${value}" ]] && echo "${default}" || echo "${value}"
}
