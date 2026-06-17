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
#     Looks up SECTION/KEY in the resolved strings file via
#     get_section_key_value. Prints DEFAULT if the strings
#     file is missing, the lookup fails, or the value is
#     empty.
#
# Github: https://github.com/007revad/Synology_drive_info
#---------------------------------------------------------

_get_text_module_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
_get_text_ui_dir="$(dirname "${_get_text_module_dir}")"

gui_lang="$(get_key_value /etc/synoinfo.conf language 2>/dev/null)"
strings_file="${_get_text_ui_dir}/texts/${gui_lang}/strings"
[[ -f "${strings_file}" ]] || strings_file="${_get_text_ui_dir}/texts/enu/strings"

txt() {
    local section="$1" key="$2" default="$3" value=""
    if [[ -f "${strings_file}" ]] && command -v get_section_key_value >/dev/null 2>&1; then
        value="$(get_section_key_value "${strings_file}" "${section}" "${key}" 2>/dev/null)"
    fi
    [[ -z "${value}" ]] && echo "${default}" || echo "${value}"
}
