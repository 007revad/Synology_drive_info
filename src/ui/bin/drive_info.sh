#!/usr/bin/env bash
#--------------------------------------------------------
# Show Synology Drive number, model and serial number
#
# Github: https://github.com/007revad/Synology_drive_info
#---------------------------------------------------------

# Check script is running as root
if [[ $( whoami ) != "root" ]]; then
    echo -e "\nERROR This script must be run as sudo or root!\n"
    exit 1  # Not running as root
fi

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
    label="$(txt volume volume_disk "Drive")"
    drive_num=""
    disk_id=""
    disk_cnr=""
    eunit=""
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
        drive_num="$label $disk_id ($eunit)"
    elif synodisk --enum -t sys | grep -q "/dev/$drive"; then
        # HD6500
        drive_num="DSM $label $disk_id"
    else
        drive_num="$label $disk_id"
    fi
}

get_nvme_num(){ 
    # Get M.2 Drive number
    local label
    label="$(txt volume volume_m2_device "M.2 Drive")"
    pcislot=""
    cardslot=""
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
        drive_num="$drive_num ($m2_card)"
    fi
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
    hdr_id="$(txt smart smart_id "ID")"
    hdr_num="$(txt volume volume_disk_number "Drive Number")"
    hdr_model="$(txt volume volume_diskmodel "Model")"
    hdr_serial="$(txt smart smart_disk_serial_title "Serial Number")"

    w_id=${#hdr_id}
    w_num=${#hdr_num}
    w_model=${#hdr_model}
    w_serial=${#hdr_serial}

    for drive in "${drives[@]}"; do
        get_drive_num
        model=$(cat "/sys/block/$drive/device/model" | xargs)
        serial=$(cat "/sys/block/$drive/device/syno_disk_serial" | xargs)
        [[ -z "$serial" ]] && serial=$(smartctl -i -d sat /dev/"$drive" | grep Serial | cut -d":" -f2 | xargs)

        ids+=("$drive"); nums+=("$drive_num"); models+=("$model"); serials+=("$serial")
        (( ${#drive}     > w_id     )) && w_id=${#drive}
        (( ${#drive_num} > w_num    )) && w_num=${#drive_num}
        (( ${#model}     > w_model  )) && w_model=${#model}
        (( ${#serial}    > w_serial )) && w_serial=${#serial}
    done

    for drive in "${nvmes[@]}"; do
        get_nvme_num
        model=$(cat "/sys/block/$drive/device/model" | xargs)
        serial=$(cat "/sys/block/$drive/device/serial" | xargs)
        [[ -z "$serial" ]] && serial=$(smartctl -i -d sat /dev/"$drive" | grep Serial | cut -d":" -f2 | xargs)

        ids+=("$drive"); nums+=("$drive_num"); models+=("$model"); serials+=("$serial")
        (( ${#drive}     > w_id     )) && w_id=${#drive}
        (( ${#drive_num} > w_num    )) && w_num=${#drive_num}
        (( ${#model}     > w_model  )) && w_model=${#model}
        (( ${#serial}    > w_serial )) && w_serial=${#serial}
    done

    sep_len=$(( w_id + 2 + w_num + 2 + w_model + 2 + w_serial ))
    echo ""
    printf '%*s\n' "$sep_len" '' | tr ' ' '-'
    printf "%-${w_id}s  %-${w_num}s  %-${w_model}s  %-${w_serial}s\n" "${hdr_id}" "${hdr_num}" "${hdr_model}" "${hdr_serial}"
    printf '%*s\n' "$sep_len" '' | tr ' ' '-'
    for i in "${!ids[@]}"; do
        printf "%-${w_id}s  %-${w_num}s  %-${w_model}s  %-${w_serial}s\n" \
            "${ids[$i]}" "${nums[$i]}" "${models[$i]}" "${serials[$i]}"
    done
fi

echo ""
