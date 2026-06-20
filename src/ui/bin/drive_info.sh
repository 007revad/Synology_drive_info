#!/usr/bin/env bash
#--------------------------------------------------------
# Show Synology Drive number, model and serial number
#
# Github: https://github.com/007revad/Synology_drive_info
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
if [[ -t 1 ]]; then
    echo "Running in an interactive shell (user terminal)."
fi

# Get DSM major version
dsm=$(/usr/syno/bin/synogetkeyvalue /etc.defaults/VERSION majorversion)

# Load translated strings if running from within the installed package.
# modules/get_text.sh and the texts/ folder won't exist if this script
# is run standalone (e.g. downloaded directly from GitHub), in which
# case fall back to printing the English defaults below.
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
get_text_module="$(dirname "${script_dir}")/modules/get_text.sh"
if [[ -f "${get_text_module}" ]]; then
    source "${get_text_module}"
else
    txt() { echo "${3}"; }  # txt SECTION KEY DEFAULT -> just print DEFAULT
fi

get_drive_num(){ 
    local label
    label="$(txt common drive "Drive")"
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
        drive_num="USB $label"
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
        drive_num="$drive_num"
        location="$m2_card"
    fi
}

get_drive_health(){ 
    local health_status
    status=""
    health_status=$(synowebapi -s --exec api="SYNO.Storage.CGI.Smart" method="get_health_info" version="1" device="\"/dev/$drive\"" \
        | jq -r '.data.healthInfo.overview.drive_status_key')
    case "$health_status" in
        normal|healthy)
            status="healthy::$(txt common status_healthy "Healthy")"
            ;;
        unc)
            status="warning::$(txt common status_warning "Warning")"  # Uncorrectable read errors
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
        status="unknown::$(txt common status_unknown "Unknown")"
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

# Add drives to drives array
for d in /sys/block/*; do
    # $d is /sys/block/sata1 etc
    case "$(basename -- "${d}")" in
        sd*|hd*)
            if [[ $d =~ [hs]d[a-z][a-z]?$ ]]; then
                drives+=("$(basename -- "${d}")")
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
                drives+=("$(basename -- "${d}")")
            fi
        ;;
    esac
done

# HDDs, SSDs and NVMe drives combined into one table
if [[ "${#drives[@]}" -gt 0 ]] || [[ "${#nvmes[@]}" -gt 0 ]]; then
    hdr_id="$(txt common id "ID")"
    hdr_num="$(txt common drive_id "Drive ID")"
    hdr_location="$(txt common location "Location")"
    hdr_model="$(txt common model "Model")"
    hdr_serial="$(txt common serial_number "Serial Number")"
    hdr_status="$(txt common status "Status")"

    w_id=${#hdr_id}
    w_num=${#hdr_num}
    w_location=${#hdr_location}
    w_model=${#hdr_model}
    w_serial=${#hdr_serial}
    w_status=${#hdr_status}

    for drive in "${drives[@]}"; do
        get_drive_num
        if [[ "$dsm" -le "6" ]]; then
            get_drive_health6
        else
            get_drive_health
        fi
        model=$(cat "/sys/block/$drive/device/model" | xargs)
        serial=$(cat "/sys/block/$drive/device/syno_disk_serial" | xargs)
        if [[ -z "$serial" ]]; then
            # Decide device type (sat/scsi) via detect_dtype()
            drive_type=$(detect_dtype)
            serial=$(smartctl -i -d "$drive_type" /dev/"$drive" | grep Serial | cut -d":" -f2 | xargs)
        fi

        ids+=("$drive"); nums+=("$drive_num"); locations+=("$location");  models+=("$model"); serials+=("$serial"); statuses+=("$status")
        (( ${#drive}     > w_id       )) && w_id=${#drive}
        (( ${#drive_num} > w_num      )) && w_num=${#drive_num}
        (( ${#location}  > w_location )) && w_location=${#location}
        (( ${#model}     > w_model    )) && w_model=${#model}
        (( ${#serial}    > w_serial   )) && w_serial=${#serial}
        (( ${#status}    > w_status   )) && w_status=${#status}
    done

    for drive in "${nvmes[@]}"; do
        get_nvme_num
        if [[ "$dsm" -le "6" ]]; then
            get_drive_health6
        else
            get_drive_health
        fi
        model=$(cat "/sys/block/$drive/device/model" | xargs)
        serial=$(cat "/sys/block/$drive/device/serial" | xargs)
        [[ -z "$serial" ]] && serial=$(smartctl -i -d sat /dev/"$drive" | grep Serial | cut -d":" -f2 | xargs)

        ids+=("$drive"); nums+=("$drive_num"); locations+=("$location"); models+=("$model"); serials+=("$serial"); statuses+=("$status")
        (( ${#drive}     > w_id       )) && w_id=${#drive}
        (( ${#drive_num} > w_num      )) && w_num=${#drive_num}
        (( ${#location}  > w_location )) && w_location=${#location}
        (( ${#model}     > w_model    )) && w_model=${#model}
        (( ${#serial}    > w_serial   )) && w_serial=${#serial}
        (( ${#status}    > w_status   )) && w_status=${#status}
    done

    sep_len=$(( w_id + 2 + w_num + 2 + w_location + 2 + w_model + 2 + w_serial + 2 + w_status ))
    echo ""
    printf '%*s\n' "$sep_len" '' | tr ' ' '-'
    printf "%-${w_id}s  %-${w_num}s  %-${w_location}s  %-${w_model}s  %-${w_serial}s  %-${w_status}s\n" \
        "${hdr_id}" "${hdr_num}" "${hdr_location}" "${hdr_model}" "${hdr_serial}" "${hdr_status}"
    printf '%*s\n' "$sep_len" '' | tr ' ' '-'
    for i in "${!ids[@]}"; do
        printf "%-${w_id}s  %-${w_num}s  %-${w_location}s  %-${w_model}s  %-${w_serial}s  %-${w_status}s\n" \
            "${ids[$i]}" "${nums[$i]}" "${locations[$i]}" "${models[$i]}" "${serials[$i]}" "${statuses[$i]}"
    done
fi

echo ""
