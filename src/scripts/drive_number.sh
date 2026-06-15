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

Yellow='\e[0;33m'   # ${Yellow}
Cyan='\e[0;36m'     # ${Cyan}
Off='\e[0m'         # ${Off}

get_drive_num(){ 
    # Get Drive number
    disk_id=""
    disk_id=$(synodisk --get_location_form "/dev/$drive" | grep 'Disk id' | awk '{print $NF}')
    drive_num="Drive $disk_id"
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

show_drive_model(){ 
    # Get drive model
    # $drive is sata1 or sda or usb1 etc
    model=$(cat "/sys/block/$drive/device/model")
    model=$(printf "%s" "$model" | xargs)  # trim leading and trailing white space

    # Get drive serial number
    if echo "$drive" | grep nvme >/dev/null ; then
        serial=$(cat "/sys/block/$drive/device/serial")
    else
        serial=$(cat "/sys/block/$drive/device/syno_disk_serial")
    fi
    serial=$(printf "%s" "$serial" | xargs)  # trim leading and trailing white space

    # Get drive serial number with smartctl for USB drives
#    if [[ -z "$serial" && "${drive:0:4}" != "nvme" ]]; then
    if [[ -z "$serial" ]]; then
        serial=$(smartctl -i -d sat /dev/"$drive" | grep Serial | cut -d":" -f2 | xargs)
    fi

    # Show drive model and serial
    printf "%s\t%s\t%s\t%s\n" "$drive" "$drive_num" "$model" "$serial"
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
        #usb*)
        #    if [[ $d =~ usb[0-9]?[0-9]?$ ]]; then
        #        drives+=("$(basename -- "${d}")")
        #    fi
        #;;
    esac
done

if [[ -z "$errtotal" ]]; then errtotal=0 ; fi

# HDDs and SSDs
if [[ "${#drives[@]}" -gt 0 ]]; then
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

    sep_len=$(( w_id + 2 + w_num + 2 + w_model + 2 + w_serial ))
    echo ""
    printf '%*s\n' "$sep_len" '' | tr ' ' '-'
    printf "%-${w_id}s  %-${w_num}s  %-${w_model}s  %-${w_serial}s\n" "ID" "Number" "Model" "Serial"
    printf '%*s\n' "$sep_len" '' | tr ' ' '-'
    for i in "${!ids[@]}"; do
        printf "%-${w_id}s  ${Cyan}%-${w_num}s${Off}  %-${w_model}s  ${Yellow}%-${w_serial}s${Off}\n" \
            "${ids[$i]}" "${nums[$i]}" "${models[$i]}" "${serials[$i]}"
    done
fi

# M.2 drives
if [[ "${#nvmes[@]}" -gt 0 ]]; then
    w_id=2
    w_num=6
    w_model=5
    w_serial=6

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
        printf "%-${w_id}s  ${Cyan}%-${w_num}s${Off}  %-${w_model}s  ${Yellow}%-${w_serial}s${Off}\n" \
            "${ids[$i]}" "${nums[$i]}" "${models[$i]}" "${serials[$i]}"
    done
fi

echo ""

