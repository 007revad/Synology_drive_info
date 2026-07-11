#!/usr/bin/env bash
# shellcheck disable=SC2002,SC1090,SC2207
#--------------------------------------------------------
# Show Synology Drive number, model and serial number etc
#
# Github: https://github.com/007revad/Synology_drive_info
#--------------------------------------------------------
# SMR drives
# https://www.truenas.com/community/resources/list-of-known-smr-drives.141/
# https://github.com/JoeSchmuck/truenas-smr-check_2025
#---------------------------------------------------------

if [[ -d /var/packages/drive_info/var ]]; then
    log="yes"
    #logfile=/var/packages/drive_info/var/drive_info_debug.log
    logfile=/var/packages/drive_info/target/var/drive_info_debug.log
fi

# Check script is running as root
if [[ $( whoami ) != "root" ]]; then
    echo -e "\nERROR This script must be run as sudo or root!\n"
    exit 1  # Not running as root
fi

# Check if script is running in an interactive shell
if [[ -t 1 ]]; then  # Running in terminal
    echo "Running in an interactive shell (user terminal)."
fi

# Get DSM major version
dsm=$(/usr/syno/bin/synogetkeyvalue /etc.defaults/VERSION majorversion)

# Get smartctl location and check if version 7
if which smartctl7 >/dev/null; then
    # smartmontools 7 from SynoCli Disk Tools is installed
    smartctl=$(which smartctl7)
    smartversion=7
else
    smartctl=$(which smartctl)
fi

# Check if language entries exist in sudoers file, regardless of (ALL) vs (root)
if [[ "$dsm" -ge "7" ]]; then
    if ! grep -q "drive_info.sh enu" /etc/sudoers.d/drive_info 2>/dev/null; then
        # Update sudoers to support language argument
        pkg=drive_info
        file=/etc/sudoers.d/drive_info
        script=/var/packages/drive_info/target/ui/bin/drive_info.sh
        echo -n "" > "$file"
        for lang in chs cht csy dan enu fre ger hun ita jpn krn nld nor plk ptb ptg rus spn sve tha trk; do
            echo "$pkg ALL=(root) NOPASSWD: $script $lang" >> "$file"
        done
        echo "$pkg ALL=(root) NOPASSWD: $script" >> "$file"
        chmod 0440 "$file"
    fi
fi

# Add smart_info entries to sudoers.d if missing
if [[ "$dsm" -ge "7" ]]; then
    if ! grep -q "smart_info.sh --dev=/dev/sd" /etc/sudoers.d/drive_info 2>/dev/null || \
       ! grep -q "smart_info.sh --dev=/dev/usb" /etc/sudoers.d/drive_info 2>/dev/null; then
        pkg=drive_info
        file=/etc/sudoers.d/drive_info
        script=/var/packages/drive_info/target/ui/bin/smart_info.sh
        for flags in "" "-i" "-a" "-ia"; do
            for dev in sd hd sata sas nvme nvc usb; do
                if [[ -n "$flags" ]]; then
                    echo "$pkg ALL=(root) NOPASSWD: $script $flags --dev=/dev/${dev}*" >> "$file"
                else
                    echo "$pkg ALL=(root) NOPASSWD: $script --dev=/dev/${dev}*" >> "$file"
                fi
            done
        done
        chmod 0440 "$file"
    fi
fi

# Remove duplicate lines from sudoers.d file
if [[ "$dsm" -ge "7" ]]; then
    awk '!seen[$0]++' /etc/sudoers.d/drive_info > /tmp/drive_info.clean
    chmod 0440 /tmp/drive_info.clean
    cp /tmp/drive_info.clean /etc/sudoers.d/drive_info
fi

# Check if 1st argument is a DSM language code
if [[ $1 =~ chs|cht|csy|dan|enu|fre|ger|hun|ita|jpn|krn|nld|nor|plk|ptb|ptg|rus|spn|sve|tha|trk ]]; then
    gui_lang="$1"
else
    gui_lang=""
fi

# Load translated strings if running from within the installed package.
# modules/get_text.sh and the texts/ folder won't exist if this script
# is run standalone (e.g. downloaded directly from GitHub), in which
# case fall back to printing the English defaults below.
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
get_text_module="$(dirname "${script_dir}")/modules/get_text.sh"
if [[ -f "${get_text_module}" ]]; then
    source "${get_text_module}" "$gui_lang"
else
    txt() { echo "${3}"; }  # txt SECTION KEY DEFAULT -> just print DEFAULT
fi

not_flash_drive(){ 
    # $1 is /sys/block/sata1 /sys/block/usb1 etc
    # Check if drive is flash drive (not supported by smartctl)
    removable=$(cat "${1}/removable")
    capability=$(cat "${1}/capability")
    if [[ $removable == "1" ]] && [[ $capability == "51" ]]; then
        return 1
    fi
}

is_usb(){ 
    # $1 is /dev/sda or /sys/block/sda etc
    if realpath /sys/block/"$(basename "$1")" | grep -q usb; then
        return 0
    else
        return 1
    fi
}

get_drive_num(){ 
    local label usb_drive_label
    label="$(txt common drive "Drive")"
    usb_drive_label="$(txt common usb_drive "USB Drive")"
    drive_num=""
    disk_id=""
    disk_cnr=""
    eunit=""
    location=""
    # Get Drive number
    disk_id=$(synodisk --get_location_form "/dev/$drive" | grep 'Disk id:' | awk '{print $NF}')
    disk_cnr=$(synodisk --get_location_form "/dev/$drive" | grep 'Disk cnr:' | awk '{print $NF}')

    # Get eunit model and port number
    # Only device tree models have syno_slot_mapping so we use different method
    # /tmp/eunitinfo_2 example contents:
    #  EUnitModel=DX213-2
    #  EUnitDisks=/dev/sdja,/dev/sdjb
    for f in /tmp/eunitinfo_*; do
        if [[ -f "$f" ]]; then
            if grep -q "/dev/$drive" "$f"; then
                eunit="$(get_key_value "$f" EUnitModel)"
            fi
        fi
    done

    if [[ $disk_cnr -eq "4" ]]; then
        usb_num="$(synousbdisk -info "$drive" | grep '^Name:' | cut -d" " -f4)"
        drive_num="$usb_drive_label $usb_num"
    elif [[ $eunit ]]; then
        #drive_num="$label $disk_id ($eunit)"
        drive_num="$label $disk_id"
        location="$eunit"
    elif synodisk --enum -t sys | grep -q "/dev/$drive"; then
        # HD6500
        drive_num="$label $disk_id"
        location="$(txt common system_drive "System Drive")"
    else
        drive_num="$label $disk_id"
    fi

    # Get PCIe M.2 card model (if the drive is an M.2 SATA drive in a PCIe M.2 card)
    if [[ "$drive" =~ nvc ]]; then
        m2_card="$(synonvme --m2-card-model-get /dev/"$drive")"
        if ! echo "$m2_card" | grep -q 'Not M.2 adapter card'; then
            location="$m2_card"
        fi
    fi
}

get_nvme_num(){ 
    # Get M.2 Drive number
    local label
    label="$(txt common m2_drive "M.2 Drive")"
    pcislot=""
    cardslot=""
    location=""
    if nvme=$(synonvme --get-location "/dev/$drive"); then
        if [[ ! $nvme =~ "PCI Slot: 0" ]]; then
            pcislot="$(echo "$nvme" | cut -d"," -f2 | awk '{print $NF}')-"
        fi
        cardslot="$(echo "$nvme" | awk '{print $NF}')"
    else
        pcislot="$(basename -- "$drive")"
        cardslot=""
    fi
    drive_num="$label $pcislot$cardslot"

    # Get PCIe M.2 card model (if the drive is in a PCIe M.2 card, not onboard)
    m2_card="$(synonvme --m2-card-model-get /dev/"$drive")"
    if ! echo "$m2_card" | grep -q 'Not M.2 adapter card'; then
        #drive_num="$drive_num ($m2_card)"
        location="$m2_card"
    fi
}

append_pool_hover(){ 
    # Appends "@@<pool label>" to drive_num when the drive is a storage pool
    # member, so api.cgi can turn it into a hover tooltip. Stripped when
    # running in a terminal (no hover there).
    local pool_label="${disk_pool_map[$drive]}"
    [[ -n "$pool_label" ]] && drive_num="${drive_num}@@${pool_label}"
    if [[ -t 1 ]]; then  # Running in terminal
        drive_num="${drive_num%%@@*}"
    fi
}

get_drive_health(){ 
    local health_status
    status=""
    if [[ $1 == "usb" ]]; then
        health_status=$(synousbdisk -info "$drive" | grep '^Status:' | cut -d" " -f2)
    else
        if [[ "$dsm" -le "6" ]]; then
            # This works in DSM 6 but takes 31 seconds for 8 drives!
            # The get_drive_health6 method only takes 4 seconds for 8 drives
            health_status=$(synowebapi --exec api="SYNO.Storage.CGI.Smart" method="get_health_info" version="1" device="\"/dev/$drive\"" 2>/dev/null \
                | jq -r '.data.healthInfo.overview.overview_status')
        else
            health_status=$(synowebapi -s --exec api="SYNO.Storage.CGI.Smart" method="get_health_info" version="1" device="\"/dev/$drive\"" 2>/dev/null \
                | jq -r '.data.healthInfo.overview.drive_status_key')
        fi

        # If webapi returned nothing, fall back to DSM 6.1 cache method
        if [[ -z "$health_status" ]] || [[ "$health_status" == "null" ]]; then
            get_drive_health6
            return
        fi
    fi

    case "$health_status" in
        normal|healthy)
            # healthy:: shows in green
            status="healthy::$(txt common status_healthy "Healthy")"
            ;;
        unc)
            # warning:: shows in orange/yellow
            status="warning::$(txt common status_warning "Warning")"  # Uncorrectable read errors
            ;;
        warning)
            # warning:: shows in orange/yellow
            status="warning::$(txt common status_warning "Warning")"
            ;;
        critical)
            # critical:: shows in red
            status="critical::$(txt common status_critical "Critical")"
            ;;
        failing)
            # failing:: shows in red
            status="failing::$(txt common status_failing "Failing")"
            ;;
        # TODO: confirm what drive_status_key returns for access error
        # disk_status_access_err = "Access Error" exists in DSM strings
        # but the actual key value is unconfirmed
        #disk_status_access_err)
            # warning:: shows in orange/yellow
        #    status="warning::$(txt common status_access_error "Access Error")"
        #    ;;
        data_detected)
            # critical:: shows in red
            status="critical::$(txt common status_data_detected "Detected")"
            ;;
        disknotsupported)
            # warning:: shows in orange/yellow
            status="warning::$(txt common status_unsupported "Not supported")"
            ;;
        disabled)
            status="$(txt common status_disabled "Disabled")"
            ;;
        unknown)
            status="$(txt common status_unknown "Unknown")"
            ;;
        *)
            status="Unknown ($health_status)"
            ;;
    esac
    if [[ -t 1 ]]; then         # Running in terminal
        status="${status#*::}"  # Remove 'healthy::' etc
    fi
}

# DSM 6's SYNO.Storage.CGI.Smart webapi is non-functional (returns error 104 unconditionally
# regardless of params/version/runner) and so the health status is instead read directly
# from synostoraged's live cache at /run/synostorage/disks/<dev>/{smart,adv_status}
get_drive_health6(){ 
    local cache_dir="/run/synostorage/disks/${drive}"
    local smart adv_status health_status
    status=""

    if [[ ! -d "$cache_dir" ]]; then
        #status="unknown::$(txt common status_unknown "Unknown")"
        status="$(txt common status_unknown "Unknown")"
    else
        smart=$(<"${cache_dir}/smart")
        adv_status=$(<"${cache_dir}/adv_status")

        if [[ "$adv_status" == "failing" ]]; then
            health_status="failing"
        elif [[ "$smart" == "fail" || "$adv_status" == "critical" ]]; then
            health_status="critical"
        elif [[ "$adv_status" == "warning" ]]; then
            health_status="warning"
        else
            health_status="healthy"
        fi

        case "$health_status" in
            healthy)
                status="healthy::$(txt common status_healthy "Healthy")"
                ;;
            warning)
                status="warning::$(txt common status_warning "Warning")"
                ;;
            critical)
                status="critical::$(txt common status_critical "Critical")"
                ;;
            failing)
                status="failing::$(txt common status_failing "Failing")"
                ;;
        esac
    fi

    if [[ -t 1 ]]; then         # Running in terminal
        status="${status#*::}"  # Remove 'healthy::' etc
    fi
}

detect_dtype(){ 
    # Default to SAT
    local dtype="sat"

    # If SAS appears at least once, treat as SCSI
    if [ "$("$smartctl" -i /dev/"$drive" 2>/dev/null | grep -c SAS)" -gt 0 ]; then
        dtype="scsi"
    # Else if SATA appears at least once, treat as SAT
    elif [ "$("$smartctl" -i /dev/"$drive" 2>/dev/null | grep -c SATA)" -gt 0 ]; then
        dtype="sat"
    fi

    echo "$dtype"
}

c2f(){ 
    # Celsius to Fahrenheit 
    # F = (C x 9/5) + 32
    local a b d f

    a=$(echo "${1%.*}" | awk '{print ($1 * 1.8)}')
    #echo "a: $a"  # debug

    if [[ $1 == *.* ]]; then
        d="${1##*.}"
    fi
    if [[ ${#d} -eq 1 ]]; then
        b=$(echo "${1##*.}" | awk '{print (($1 * 1.8) / 10)}')
    elif [[ ${#d} -eq 2 ]]; then
        b=$(echo "${1##*.}" | awk '{print (($1 * 1.8) / 100)}')
    elif [[ ${#d} -eq 3 ]]; then
        b=$(echo "${1##*.}" | awk '{print (($1 * 1.8) / 1000)}')
    fi
    #echo "b: $b"  # debug

    if [[ -n $b ]]; then
        f=$(echo "$a" "$b" | awk '{print (($1 + $2) + 32)}')
    else
        f=$(echo "$a" | awk '{print ($1 + 32)}')
    fi
    #echo "f: $f"  # debug

    fahrenheit="$f"
}

get_drive_temp(){ 
    local raw celsius fahrenheit_rounded
    # Tempeture is a Synology typo in synodisk output
    raw=$(synodisk --info /dev/"$drive" | grep 'Tempeture' | cut -d" " -f3)
    celsius="${raw%.*}"  # Remove decimal places that are always .00
    c2f "$celsius"
    fahrenheit_rounded=$(printf '%.0f' "$fahrenheit")
    temp="${celsius}°C / ${fahrenheit_rounded}°F"
}

get_drive_size(){ 
    local size_tb size_gb size_mb size_bytes sector_size
    size_tb="$(txt common size_tb "TiB")"
    size_gb="$(txt common size_gb "GiB")"
    size_mb="$(txt common size_mb "MiB")"

    # Format total size (auto TiB/GiB/MiB)
    size_sectors="$(cat /sys/block/"$drive"/size)"
    # Linux's /sys/block/<disk>/size is always counted in 512-byte units,
    # even on native 4Kn drives where logical_block_size reports 4096
    #sector_size="$(cat "/sys/block/$drive/queue/logical_block_size")"
    #size_bytes=$(( size_sectors * sector_size ))
    size_bytes=$(( size_sectors * 512 ))
    size=$(awk -v b="$size_bytes" -v tib_u="$size_tb" -v gib_u="$size_gb" -v mib_u="$size_mb" 'BEGIN {
        tib = b / (1024^4)
        gib = b / (1024^3)
        mib = b / (1024^2)
        if (tib >= 1)      { printf "%.1f %s", tib, tib_u }
        else if (gib >= 1) { printf "%.1f %s", gib, gib_u }
        else               { printf "%.1f %s", mib, mib_u }
    }')
}

check_drive_smr(){ 
    # https://www.truenas.com/community/resources/list-of-known-smr-drives.141/
    local smr_type vendor model
    local smr_drive_list_file="/var/packages/drive_info/target/ui/bin/smr_drive_list.txt"
    local ha-smr_drive_list_file="/var/packages/drive_info/target/ui/bin/ha-smr_drive_list.txt"
    local hm-smr_drive_list_file="/var/packages/drive_info/target/ui/bin/hm-smr_drive_list.txt"

    model=$(cat "/sys/block/$drive/device/model" | xargs)
    vendor=$(cat "/sys/block/$drive/device/vendor" 2>/dev/null | xargs)
    smr_check="$($smartctl -d "$drive_type" --identify=wb /dev/"$drive" | grep Zoned | awk '{print $3}')"
    if [[ "$smr_check" == "0x1b" || "$smr_check" == "0x01b" ]]; then
        smr_type="HA-SMR"
    elif [[ "$smr_check" == "0x10b" ]]; then
        #smr_type="DM-SMR"
        smr_type="SMR"
    elif grep -qFf "$ha-smr_drive_list_file" <<< "$model" \
        || grep -qFf "$ha-smr_drive_list_file" <<< "$vendor$model"; then
        smr_type="HA-SMR"
    elif grep -qFf "$hm-smr_drive_list_file" <<< "$model" \
        || grep -qFf "$hm-smr_drive_list_file" <<< "$vendor$model"; then
        smr_type="HM-SMR"
    elif grep -qFf "$smr_drive_list_file" <<< "$model" \
        || grep -qFf "$smr_drive_list_file" <<< "$vendor$model"; then
        #smr_type="DM-SMR"
        smr_type="SMR"
    #else
    #    echo "may be HM-SMR... ???"
    fi
    
    echo "$smr_type"
}

fixdrivemodel(){ 
    local hdmodel="$1"

    # Remove " 00Y" from end of Samsung/Lenovo SSDs  # Github issue #13
    if [[ $hdmodel =~ MZ.*' 00Y' ]]; then
        hdmodel=$(printf "%s" "$hdmodel" | sed 's/ 00Y.*//')
    fi

    # Brands that return "BRAND <model>" and need "BRAND " removed.
    if [[ $hdmodel =~ ^[A-Za-z]{3,7}' '.* ]]; then
        # See  Smartmontools database in /var/lib/smartmontools/drivedb.db
        hdmodel=${hdmodel#"WDC "}       # Remove "WDC " from start of model name
        hdmodel=${hdmodel#"HGST "}      # Remove "HGST " from start of model name
        hdmodel=${hdmodel#"TOSHIBA "}   # Remove "TOSHIBA " from start of model name

        # Chinese brand?
        hdmodel=${hdmodel#"HCST "}      # Remove "HCST " from start of model name. Issue #389

        # Old drive brands
        hdmodel=${hdmodel#"Hitachi "}   # Remove "Hitachi " from start of model name
        hdmodel=${hdmodel#"SAMSUNG "}   # Remove "SAMSUNG " from start of model name
        hdmodel=${hdmodel#"FUJISTU "}   # Remove "FUJISTU " from start of model name
        
        # Remove any leading spaces
        hdmodel=$(echo "$hdmodel" | sed -e 's/^[[:space:]]*//')
    elif [[ $hdmodel =~ ^'APPLE HDD '.* ]]; then
        # Old drive brands
        hdmodel=${hdmodel#"APPLE HDD "} # Remove "APPLE HDD " from start of model name
        
        # Remove any leading spaces
        hdmodel=$(echo "$hdmodel" | sed -e 's/^[[:space:]]*//')
    fi

    echo "$hdmodel"
}

# Fetch storage pool info once, up front, so both the drive table (pool-membership
# hover) and get_volume_info() (member-disks hover) can reuse the same data
# instead of each calling synowebapi separately.
if [[ "$dsm" -le "6" ]]; then
    storage_json=$(synowebapi --exec api=SYNO.Storage.CGI.Storage method=load_info version=1 2>/dev/null)
else
    storage_json=$(synowebapi -s --exec api=SYNO.Storage.CGI.Storage method=load_info version=1 2>/dev/null)
fi
if [[ -z "$storage_json" ]] || ! echo "$storage_json" | jq -e '.success' >/dev/null 2>&1; then
    storage_json=""
fi

# Build disk id -> storage pool label (e.g. "sata1" -> "Storage Pool 1")
declare -A disk_pool_map
if [[ -n "$storage_json" ]]; then
    pool_label_prefix="$(txt common storage_pool "Storage Pool")"
    while IFS='|' read -r pool_num_id pool_disks_raw; do
        IFS=',' read -ra _pool_disk_ids <<< "$pool_disks_raw"
        for _did in "${_pool_disk_ids[@]}"; do
            [[ -z "$_did" ]] && continue
            disk_pool_map["$_did"]="$pool_label_prefix $pool_num_id"
        done
    done < <(echo "$storage_json" | jq -r '.data.storagePools[] | "\(.num_id)|\(.disks | join(","))"')
fi

# Add drives to drives array
for d in /sys/block/*; do
    # $d is /sys/block/sata1 etc
    case "$(basename -- "${d}")" in
        sd*|hd*)
            if [[ $d =~ [hs]d[a-z][a-z]?$ ]]; then
                if is_usb "$d"; then  # Add USB drives except flash drives
                    if not_flash_drive "$d"; then
                        usbs+=("$(basename -- "${d}")")
                    fi
                else
                    drives+=("$(basename -- "${d}")")  # Add all other drives
                fi
            fi
        ;;
        sata*|sas*)
            if [[ $d =~ (sas|sata)[0-9][0-9]?[0-9]?$ ]]; then
                drives+=("$(basename -- "${d}")")
            fi
        ;;
        nvme*)
            if [[ $d =~ nvme[0-9][0-9]?n[0-9][0-9]?$ ]]; then
                nvmes+=("$(basename -- "${d}")")
            fi
        ;;
        nvc*)  # M.2 SATA drives (in PCIe card only?)
            if [[ $d =~ nvc[0-9][0-9]?$ ]]; then
                nvcs+=("$(basename -- "${d}")")
            fi
        ;;
        usb*)
            if [[ $d =~ usb[0-9]?[0-9]?$ ]]; then
                if not_flash_drive "$d"; then
                    usbs+=("$(basename -- "${d}")")
                fi
            fi
        ;;
    esac
done

# Sort drives array numerically/version-aware
IFS=$'\n' drives=($(printf '%s\n' "${drives[@]}" | sort -V))
IFS=$'\n' nvmes=($(printf '%s\n' "${nvmes[@]}" | sort -V))
IFS=$'\n' nvcs=($(printf '%s\n' "${nvcs[@]}" | sort -V))
IFS=$'\n' usbs=($(printf '%s\n' "${usbs[@]}" | sort -V))

# HDDs, SSDs and NVMe drives combined into one table
if [[ "${#drives[@]}" -gt 0 ]] || [[ "${#nvmes[@]}" -gt 0 ]] ||\
        [[ "${#nvcs[@]}" -gt 0 ]] || [[ "${#usbs[@]}" -gt 0 ]]; then
    hdr_id="$(txt common id "ID")"
    hdr_num="$(txt common drive_id "Drive ID")"
    hdr_location="$(txt common location "Location")"
    hdr_model="$(txt common model "Model")"
    hdr_size="$(txt common size "Size")"
    hdr_smr="$(txt common smr "SMR")"
    hdr_serial="$(txt common serial_number "Serial Number")"
    hdr_temp="$(txt common temperature "Temperature")"
    #hdr_temp="$(txt common temperature "°C")"
    hdr_status="$(txt common status "Status")"

    w_id=${#hdr_id}
    w_num=${#hdr_num}
    w_location=${#hdr_location}
    w_model=${#hdr_model}
    w_size=${#hdr_size}
    w_smr=${#hdr_smr}
    w_serial=${#hdr_serial}
    w_temp=${#hdr_temp}
    w_status=${#hdr_status}

    smr=""

    for drive in "${drives[@]}"; do
        get_drive_num
        append_pool_hover
        if [[ "$dsm" -le "6" ]]; then
            get_drive_health6
        else
            get_drive_health
        fi
        model=$(cat "/sys/block/$drive/device/model" | xargs)
        serial=$(cat "/sys/block/$drive/device/syno_disk_serial" | xargs)
        # Decide device type (sat/scsi) via detect_dtype()
        drive_type=$(detect_dtype)
        if [[ -z "$serial" ]]; then
            serial=$("$smartctl" -i -d "$drive_type" /dev/"$drive" | grep Serial | cut -d":" -f2 | xargs)
        fi

        get_drive_size
        smr=$(check_drive_smr)
        get_drive_temp

        ids+=("$drive"); nums+=("$drive_num"); locations+=("$location"); models+=("$model"); sizes+=("$size"); smrs+=("$smr"); serials+=("$serial"); temps+=("$temp"); statuses+=("$status")
        (( ${#drive}     > w_id       )) && w_id=${#drive}
        (( ${#drive_num} > w_num      )) && w_num=${#drive_num}
        (( ${#location}  > w_location )) && w_location=${#location}
        (( ${#model}     > w_model    )) && w_model=${#model}
        (( ${#size}      > w_size     )) && w_size=${#size}
        (( ${#smr}       > w_smr      )) && w_smr=${#smr}
        (( ${#serial}    > w_serial   )) && w_serial=${#serial}
        (( ${#temp}      > w_temp     )) && w_temp=${#temp}
        (( ${#status}    > w_status   )) && w_status=${#status}
    done

    for drive in "${nvmes[@]}"; do
        get_nvme_num
        append_pool_hover
        if [[ "$dsm" -le "6" ]]; then
            get_drive_health6
        else
            get_drive_health
        fi
        model=$(cat "/sys/block/$drive/device/model" | xargs)
        serial=$(cat "/sys/block/$drive/device/serial" | xargs)
        [[ -z "$serial" ]] && serial=$("$smartctl" -i -d sat /dev/"$drive" | grep Serial | cut -d":" -f2 | xargs)

        get_drive_size
        get_drive_temp

        ids+=("$drive"); nums+=("$drive_num"); locations+=("$location"); models+=("$model"); sizes+=("$size"); smrs+=("$smr"); serials+=("$serial"); temps+=("$temp"); statuses+=("$status")
        (( ${#drive}     > w_id       )) && w_id=${#drive}
        (( ${#drive_num} > w_num      )) && w_num=${#drive_num}
        (( ${#location}  > w_location )) && w_location=${#location}
        (( ${#model}     > w_model    )) && w_model=${#model}
        (( ${#size}      > w_size     )) && w_size=${#size}
        (( ${#smr}       > w_smr      )) && w_smr=${#smr}
        (( ${#serial}    > w_serial   )) && w_serial=${#serial}
        (( ${#temp}      > w_temp     )) && w_temp=${#temp}
        (( ${#status}    > w_status   )) && w_status=${#status}
    done

    for drive in "${nvcs[@]}"; do
        get_drive_num
        append_pool_hover
        if [[ "$dsm" -le "6" ]]; then
            get_drive_health6
        else
            get_drive_health
        fi
        model=$(cat "/sys/block/$drive/device/model" | xargs)
        serial=$(cat "/sys/block/$drive/device/syno_disk_serial" | xargs)
        [[ -z "$serial" ]] && serial=$("$smartctl" -i -d sat /dev/"$drive" | grep Serial | cut -d":" -f2 | xargs)

        get_drive_size
        get_drive_temp

        ids+=("$drive"); nums+=("$drive_num"); locations+=("$location"); models+=("$model"); sizes+=("$size"); smrs+=("$smr"); serials+=("$serial"); temps+=("$temp"); statuses+=("$status")
        (( ${#drive}     > w_id       )) && w_id=${#drive}
        (( ${#drive_num} > w_num      )) && w_num=${#drive_num}
        (( ${#location}  > w_location )) && w_location=${#location}
        (( ${#model}     > w_model    )) && w_model=${#model}
        (( ${#size}      > w_size     )) && w_size=${#size}
        (( ${#smr}       > w_smr      )) && w_smr=${#smr}
        (( ${#serial}    > w_serial   )) && w_serial=${#serial}
        (( ${#temp}      > w_temp     )) && w_temp=${#temp}
        (( ${#status}    > w_status   )) && w_status=${#status}
    done

    for drive in "${usbs[@]}"; do
        get_drive_num
        append_pool_hover
        get_drive_health usb
        #model=$(cat "/sys/block/$drive/device/model" | xargs)
        model=$(smartctl -i -d sat /dev/"$drive" | grep '^Device Model:' | cut -d":" -f2 | xargs)
        model=$(fixdrivemodel "$model")

        serial=$(cat "/sys/block/$drive/device/syno_disk_serial" | xargs)
        # Decide device type (sat/scsi) via detect_dtype()
        drive_type=$(detect_dtype)
        if [[ -z "$serial" ]]; then
            serial=$("$smartctl" -i -d "$drive_type" /dev/"$drive" | grep Serial | cut -d":" -f2 | xargs)
        fi

        get_drive_size
        smr=$(check_drive_smr)
        get_drive_temp

        ids+=("$drive"); nums+=("$drive_num"); locations+=("$location"); models+=("$model"); sizes+=("$size"); smrs+=("$smr"); serials+=("$serial"); temps+=("$temp"); statuses+=("$status")
        (( ${#drive}     > w_id       )) && w_id=${#drive}
        (( ${#drive_num} > w_num      )) && w_num=${#drive_num}
        (( ${#location}  > w_location )) && w_location=${#location}
        (( ${#model}     > w_model    )) && w_model=${#model}
        (( ${#size}      > w_size     )) && w_size=${#size}
        (( ${#smr}       > w_smr      )) && w_smr=${#smr}
        (( ${#serial}    > w_serial   )) && w_serial=${#serial}
        (( ${#temp}      > w_temp     )) && w_temp=${#temp}
        (( ${#status}    > w_status   )) && w_status=${#status}
    done

    sep_len=$(( w_id + 2 + w_num + 2 + w_location + 2 + w_model + 2 + w_size + 2 + w_smr + 2 + w_serial + 2 + w_temp + 2 + w_status ))
    echo ""
    printf '%*s\n' "$sep_len" '' | tr ' ' '-'
    printf "%-${w_id}s  %-${w_num}s  %-${w_location}s  %-${w_model}s  %-${w_size}s  %-${w_smr}s  %-${w_serial}s  %-${w_temp}s  %-${w_status}s\n" \
        "${hdr_id}" "${hdr_num}" "${hdr_location}" "${hdr_model}" "${hdr_size}" "${hdr_smr}" "${hdr_serial}" "${hdr_temp}" "${hdr_status}"
    printf '%*s\n' "$sep_len" '' | tr ' ' '-'
    for i in "${!ids[@]}"; do
        printf "%-${w_id}s  %-${w_num}s  %-${w_location}s  %-${w_model}s  %-${w_size}s  %-${w_smr}s  %-${w_serial}s  %-${w_temp}s  %-${w_status}s\n" \
            "${ids[$i]}" "${nums[$i]}" "${locations[$i]}" "${models[$i]}" "${sizes[$i]}" "${smrs[$i]}" "${serials[$i]}" "${temps[$i]}" "${statuses[$i]}"
    done
fi

echo ""

# Volume information table
get_volume_info(){ 
    local storage_json="$storage_json"
    if [[ -z "$storage_json" ]] || ! echo "$storage_json" | jq -e '.success' >/dev/null 2>&1; then
        return 1
    fi

    # Build disk id -> friendly name lookup (e.g. "sata1" -> "Drive 3")
    declare -A disk_name_map
    while IFS='|' read -r disk_id disk_name; do
        disk_name_map["$disk_id"]="$disk_name"
    done < <(echo "$storage_json" | jq -r '.data.disks[]? | "\(.id)|\(.name)"')

    # Build pool lookup: pool id -> num_id, pool status, RAID device_type and member disks
    declare -A pool_num pool_status_map pool_pct_map pool_devtype_map pool_disks_map
    while IFS='|' read -r pool_id pool_num_id pool_st pool_scrub pool_pct pool_devtype pool_disks_raw; do
        pool_num["$pool_id"]="$pool_num_id"
        local scrub_suffix=""
        [[ "$pool_scrub" == "scrubbing" ]] && scrub_suffix=" - Data Scrubbing"
        pool_status_map["$pool_id"]="${pool_st}${scrub_suffix}"
        pool_pct_map["$pool_id"]="$pool_pct"
        pool_devtype_map["$pool_id"]="$pool_devtype"

        # Translate raw disk ids (e.g. sata1) to friendly names (e.g. Drive 3)
        local disk_ids=() disk_names=() did joined=""
        IFS=',' read -ra disk_ids <<< "$pool_disks_raw"
        for did in "${disk_ids[@]}"; do
            [[ -z "$did" ]] && continue
            [[ -n "$joined" ]] && joined+=", "
            joined+="${disk_name_map[$did]:-$did}"
        done
        pool_disks_map["$pool_id"]="$joined"
    done < <(echo "$storage_json" | jq -r '.data.storagePools[] | "\(.id)|\(.num_id)|\(.status)|\(.scrubbingStatus // "")|\(.progress.percent // "-1")|\(.device_type // "")|\(.disks | join(","))"')

    local hdr_vol hdr_pool hdr_raid hdr_size hdr_pct hdr_status hdr_pool_status
    hdr_vol="$(txt common volume "Volume")"
    hdr_pool="$(txt common storage_pool "Storage Pool")"
    hdr_raid="$(txt common raid_type "RAID")"
    hdr_size="$(txt common volume_size "Volume Size")"
    hdr_pct="$(txt common volume_used "Used")"
    hdr_status="$(txt common status "Status")"
    hdr_pool_status="$(txt common storage_status "Storage Status")"

    local w_vol w_pool w_raid w_size w_pct w_status w_pool_status
    w_vol=${#hdr_vol}
    w_pool=${#hdr_pool}
    w_raid=${#hdr_raid}
    w_size=${#hdr_size}
    w_pct=${#hdr_pct}
    w_status=${#hdr_status}
    w_pool_status=${#hdr_pool_status}

    local vol_nums=() vol_pools=() vol_raids=() vol_sizes=() vol_pcts=() vol_statuses=() vol_pool_statuses=()

    local label_vol label_pool
    label_vol="$(txt common volume "Volume")"
    label_pool="$(txt common storage_pool "Storage Pool")"

    while IFS='|' read -r num_id pool_path total used vol_status vol_pct; do
        # Volume name
        vol_label="$label_vol $num_id"

        # Storage Pool label
        pool_label="$label_pool ${pool_num[$pool_path]}"

        # Format RAID type (from the storage pool's device_type)
        local pool_devtype raid_str
        pool_devtype="${pool_devtype_map[$pool_path]}"
        case "$pool_devtype" in
            basic)                    raid_str="$(txt common raid_basic "Basic")" ;;
            raid_linear)              raid_str="JBOD" ;;
            raid_0)                   raid_str="RAID 0" ;;
            raid_1)                   raid_str="RAID 1" ;;
            raid_5)                   raid_str="RAID 5" ;;
            raid_6)                   raid_str="RAID 6" ;;
            raid_10)                  raid_str="RAID 10" ;;
            raid_f1)                  raid_str="RAID F1" ;;
            shr_without_disk_protect) raid_str="SHR" ;;
            shr_with_1_disk_protect)  raid_str="SHR" ;;
            shr_with_2_disk_protect)  raid_str="SHR2" ;;
            *)                        raid_str="$pool_devtype" ;;
        esac

        # Append member disks after an @@ sentinel so api.cgi can turn it into
        # a hover tooltip. Stripped when running in a terminal (no hover there).
        local pool_disks
        pool_disks="${pool_disks_map[$pool_path]}"
        [[ -n "$pool_disks" ]] && raid_str="${raid_str}@@${pool_disks}"
        if [[ -t 1 ]]; then  # Running in terminal
            raid_str="${raid_str%%@@*}"
        fi

        # Format total size (auto TiB/GiB/MiB)
        local size_str size_gb size_tb size_mb
        size_tb="$(txt common size_tb "TiB")"
        size_gb="$(txt common size_gb "GiB")"
        size_mb="$(txt common size_mb "MiB")"
        size_str=$(awk -v b="$total" -v tib_u="$size_tb" -v gib_u="$size_gb" -v mib_u="$size_mb" 'BEGIN {
            tib = b / (1024^4)
            gib = b / (1024^3)
            mib = b / (1024^2)
            if (tib >= 1)      { printf "%.1f %s", tib, tib_u }
            else if (gib >= 1) { printf "%.1f %s", gib, gib_u }
            else               { printf "%.1f %s", mib, mib_u }
        }')

        # Percentage used
        local pct_str
        pct_str=$(awk -v u="$used" -v t="$total" 'BEGIN {
            if (t > 0) { printf "%d%%", (u / t * 100) }
            else       { print "0%" }
        }')

        # Volume status
        local status_str
        case "$vol_status" in
            normal)     status_str="healthy::$(txt common status_healthy "Healthy")" ;;
            degrade)    status_str="critical::$(txt common status_degraded "Degraded")" ;;
            crashed)    status_str="critical::$(txt common status_crashed "Crashed")" ;;
            repairing)  status_str="warning::$(txt common status_repairing "Repairing")" ;;
            rebuilding) status_str="warning::$(txt common status_rebuilding "Rebuilding")" ;;
            read_only)  status_str="warning::$(txt common status_read_only "Read-only")" ;;
            background|background_scrubbing) status_str="healthy::$(txt common status_healthy "Healthy")" ;;
            *)          status_str="$vol_status" ;;
        esac
        if [[ -t 1 ]]; then  # Running in terminal
            status_str="${status_str#*::}"
        fi

        if [[ "$vol_status" == "repairing" || "$vol_status" == "rebuilding" ]] \
            && [[ "$vol_pct" != "-1" && -n "$vol_pct" ]]; then
            local vol_pct_int
            vol_pct_int=$(awk -v p="$vol_pct" 'BEGIN{printf "%.0f", p}')
            status_str="${status_str} (${vol_pct_int}%)"
        fi

        # Pool status
        local pool_st pool_pct pool_status_str
        pool_st="${pool_status_map[$pool_path]}"
        pool_pct="${pool_pct_map[$pool_path]}"
        case "$pool_st" in
            normal)     pool_status_str="healthy::$(txt common status_healthy "Healthy")" ;;
            degrade)    pool_status_str="critical::$(txt common status_degraded "Degraded")" ;;
            crashed)    pool_status_str="critical::$(txt common status_crashed "Crashed")" ;;
            repairing)  pool_status_str="warning::$(txt common status_repairing "Repairing")" ;;
            rebuilding) pool_status_str="warning::$(txt common status_rebuilding "Rebuilding")" ;;
            read_only)  pool_status_str="warning::$(txt common status_read_only "Read-only")" ;;
            background|background_scrubbing) pool_status_str="healthy::$(txt common status_healthy "Healthy") - $(txt common status_data_scrubbing "Data Scrubbing")" ;;
            *)          pool_status_str="$pool_st" ;;
        esac
        if [[ -t 1 ]]; then  # Running in terminal
            pool_status_str="${pool_status_str#*::}"
        fi

        if [[ "$pool_pct" != "-1" && -n "$pool_pct" ]] \
            && [[ "$pool_st" == "repairing" || "$pool_st" == "rebuilding" \
            || "$pool_st" == "background" || "$pool_st" == "background_scrubbing" ]]; then
            local pool_pct_int
            pool_pct_int=$(awk -v p="$pool_pct" 'BEGIN{printf "%.0f", p}')
            pool_status_str="${pool_status_str} (${pool_pct_int}%)"
        fi

        vol_nums+=("$vol_label")
        vol_pools+=("$pool_label")
        vol_raids+=("$raid_str")
        vol_sizes+=("$size_str")
        vol_pcts+=("$pct_str")
        vol_statuses+=("$status_str")
        vol_pool_statuses+=("$pool_status_str")

        (( ${#vol_label}        > w_vol         )) && w_vol=${#vol_label}
        (( ${#pool_label}       > w_pool        )) && w_pool=${#pool_label}
        (( ${#raid_str}         > w_raid        )) && w_raid=${#raid_str}
        (( ${#size_str}         > w_size        )) && w_size=${#size_str}
        (( ${#pct_str}          > w_pct         )) && w_pct=${#pct_str}
        (( ${#status_str}       > w_status      )) && w_status=${#status_str}
        (( ${#pool_status_str}  > w_pool_status )) && w_pool_status=${#pool_status_str}

    done < <(echo "$storage_json" | jq -r '[.data.volumes[]] | sort_by(.num_id) | .[] | "\(.num_id)|\(.pool_path)|\(.size.total)|\(.size.used)|\(.summary_status // .status)|\(.progress.percent // "-1")"')

    if [[ "${#vol_nums[@]}" -gt 0 ]]; then
        local sep_len
        sep_len=$(( w_vol + 2 + w_pool + 2 + w_raid + 2 + w_size + 2 + w_pct + 2 + w_status + 2 + w_pool_status ))
        echo ""
        printf '%*s\n' "$sep_len" '' | tr ' ' '-'
        printf "%-${w_vol}s  %-${w_pool}s  %-${w_raid}s  %-${w_size}s  %-${w_pct}s  %-${w_status}s  %-${w_pool_status}s\n" \
            "$hdr_vol" "$hdr_pool" "$hdr_raid" "$hdr_size" "$hdr_pct" "$hdr_status" "$hdr_pool_status"
        printf '%*s\n' "$sep_len" '' | tr ' ' '-'
        for i in "${!vol_nums[@]}"; do
            printf "%-${w_vol}s  %-${w_pool}s  %-${w_raid}s  %-${w_size}s  %-${w_pct}s  %-${w_status}s  %-${w_pool_status}s\n" \
                "${vol_nums[$i]}" "${vol_pools[$i]}" "${vol_raids[$i]}" "${vol_sizes[$i]}" "${vol_pcts[$i]}" "${vol_statuses[$i]}" "${vol_pool_statuses[$i]}"
        done
    fi
}

get_volume_info

echo ""
