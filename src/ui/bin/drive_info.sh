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

get_drive_num(){ 
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
        drive_num="USB Drive  "
    elif [[ $eunit ]]; then
        drive_num="Drive $disk_id ($eunit)  "
    elif synodisk --enum -t sys | grep -q "/dev/$drive"; then
        # HD6500
        drive_num="System Drive $disk_id  "
    else
        drive_num="Drive $disk_id  "
    fi
}

get_nvme_num(){ 
    # Get M.2 Drive number
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
    drive_num="M.2 Drive $pcislot$cardslot"
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
    w_id=2
    w_num=6
    w_model=5
    w_serial=6

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
    printf "%-${w_id}s  %-${w_num}s  %-${w_model}s  %-${w_serial}s\n" "ID" "Number" "Model" "Serial"
    printf '%*s\n' "$sep_len" '' | tr ' ' '-'
    for i in "${!ids[@]}"; do
        printf "%-${w_id}s  %-${w_num}s  %-${w_model}s  %-${w_serial}s\n" \
            "${ids[$i]}" "${nums[$i]}" "${models[$i]}" "${serials[$i]}"
    done
fi

echo ""
