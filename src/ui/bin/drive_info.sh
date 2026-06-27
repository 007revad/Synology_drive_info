#!/usr/bin/env bash
#--------------------------------------------------------
# Show Synology Drive number, model and serial number etc
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
        drive_num="$drive_num"
        location="$m2_card"
    fi
}

get_drive_health(){ 
    local health_status
    status=""
    #health_status=$(synowebapi -s --exec api="SYNO.Storage.CGI.Smart" method="get_health_info" version="1" device="\"/dev/$drive\"" \
    #    | jq -r '.data.healthInfo.overview.drive_status_key')
    health_status=$(synowebapi -s --exec api="SYNO.Storage.CGI.Smart" method="get_health_info" version="1" device="\"/dev/$drive\"" 2>/dev/null \
        | jq -r '.data.healthInfo.overview.drive_status_key')

    # If webapi returned nothing, fall back to DSM 6 cache method
    if [[ -z "$health_status" ]] || [[ "$health_status" == "null" ]]; then
        get_drive_health6
        return
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
                nvcs+=("$(basename -- "${d}")")
            fi
        ;;
    esac
done

# Sort drives array numerically/version-aware
IFS=$'\n' drives=($(printf '%s\n' "${drives[@]}" | sort -V))
IFS=$'\n' nvmes=($(printf '%s\n' "${nvmes[@]}" | sort -V))
IFS=$'\n' nvcs=($(printf '%s\n' "${nvcs[@]}" | sort -V))

# HDDs, SSDs and NVMe drives combined into one table
if [[ "${#drives[@]}" -gt 0 ]] || [[ "${#nvmes[@]}" -gt 0 ]] || [[ "${#nvcs[@]}" -gt 0 ]]; then
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

    for drive in "${nvcs[@]}"; do
        get_drive_num
        if [[ "$dsm" -le "6" ]]; then
            get_drive_health6
        else
            get_drive_health
        fi
        model=$(cat "/sys/block/$drive/device/model" | xargs)
        serial=$(cat "/sys/block/$drive/device/syno_disk_serial" | xargs)
        [[ -z "$serial" ]] && serial=$(smartctl -i -d sat /dev/"$drive" | grep Serial | cut -d":" -f2 | xargs)

        ids+=("$drive"); nums+=("$drive_num"); locations+=("$location");  models+=("$model"); serials+=("$serial"); statuses+=("$status")
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

# Volume information table
get_volume_info(){
    local storage_json
    storage_json=$(synowebapi -s --exec api=SYNO.Storage.CGI.Storage method=load_info version=1 2>/dev/null)
    if [[ -z "$storage_json" ]] || ! echo "$storage_json" | jq -e '.success' >/dev/null 2>&1; then
        return 1
    fi

    # Build pool num_id lookup: pool id -> num_id
    # e.g. reuse_1 -> 1, reuse_2 -> 2
    declare -A pool_num
    while IFS='|' read -r pool_id pool_num_id; do
        pool_num["$pool_id"]="$pool_num_id"
    done < <(echo "$storage_json" | jq -r '.data.storagePools[] | "\(.id)|\(.num_id)"')

    local hdr_vol hdr_pool hdr_size hdr_pct hdr_status
    hdr_vol="$(txt common volume "Volume")"
    hdr_pool="$(txt common storage_pool "Storage Pool")"
    hdr_size="$(txt common volume_size "Volume Size")"
    hdr_pct="$(txt common volume_used "Used")"
    hdr_status="$(txt common status "Status")"

    local w_vol w_pool w_size w_pct w_status
    w_vol=${#hdr_vol}
    w_pool=${#hdr_pool}
    w_size=${#hdr_size}
    w_pct=${#hdr_pct}
    w_status=${#hdr_status}

    local vol_nums=() vol_pools=() vol_sizes=() vol_pcts=() vol_statuses=()

    local label_vol label_pool
    label_vol="$(txt common volume "Volume")"
    label_pool="$(txt common storage_pool "Storage Pool")"

    while IFS='|' read -r num_id pool_path total used vol_status; do
        # Volume name
        vol_label="$label_vol $num_id"

        # Storage Pool label
        pool_label="$label_pool ${pool_num[$pool_path]}"

        # Format total size (auto TiB/GiB/MiB)
        local size_str
        size_str=$(awk -v b="$total" 'BEGIN {
            tib = b / (1024^4)
            gib = b / (1024^3)
            mib = b / (1024^2)
            if (tib >= 1)      { printf "%.1f TiB", tib }
            else if (gib >= 1) { printf "%.1f GiB", gib }
            else               { printf "%.1f MiB", mib }
        }')

        # Percentage used
        local pct_str
        pct_str=$(awk -v u="$used" -v t="$total" 'BEGIN {
            if (t > 0) { printf "%d%%", (u / t * 100) }
            else       { print "0%" }
        }')

        # Status
        local status_str
        case "$vol_status" in
            normal)     status_str="healthy::$(txt common status_healthy "Healthy")" ;;
            degrade)    status_str="critical::$(txt common status_degraded "Degraded")" ;;
            crashed)    status_str="critical::$(txt common status_crashed "Crashed")" ;;
            repairing)  status_str="warning::$(txt common status_repairing "Repairing")" ;;
            rebuilding) status_str="warning::$(txt common status_rebuilding "Rebuilding")" ;;
            read_only)  status_str="warning::$(txt common status_read_only "Read-only")" ;;
            *)          status_str="$vol_status" ;;
        esac
        if [[ -t 1 ]]; then
            status_str="${status_str#*::}"
        fi

        vol_nums+=("$vol_label")
        vol_pools+=("$pool_label")
        vol_sizes+=("$size_str")
        vol_pcts+=("$pct_str")
        vol_statuses+=("$status_str")

        (( ${#vol_label}   > w_vol    )) && w_vol=${#vol_label}
        (( ${#pool_label}  > w_pool   )) && w_pool=${#pool_label}
        (( ${#size_str}    > w_size   )) && w_size=${#size_str}
        (( ${#pct_str}     > w_pct    )) && w_pct=${#pct_str}
        (( ${#status_str}  > w_status )) && w_status=${#status_str}

    done < <(echo "$storage_json" | jq -r '[.data.volumes[]] | sort_by(.num_id) | .[] | "\(.num_id)|\(.pool_path)|\(.size.total)|\(.size.used)|\(.summary_status // .status)"')

    if [[ "${#vol_nums[@]}" -gt 0 ]]; then
        local sep_len
        sep_len=$(( w_vol + 2 + w_pool + 2 + w_size + 2 + w_pct + 2 + w_status ))
        echo ""
        printf '%*s\n' "$sep_len" '' | tr ' ' '-'
        printf "%-${w_vol}s  %-${w_pool}s  %-${w_size}s  %-${w_pct}s  %-${w_status}s\n" \
            "$hdr_vol" "$hdr_pool" "$hdr_size" "$hdr_pct" "$hdr_status"
        printf '%*s\n' "$sep_len" '' | tr ' ' '-'
        for i in "${!vol_nums[@]}"; do
            printf "%-${w_vol}s  %-${w_pool}s  %-${w_size}s  %-${w_pct}s  %-${w_status}s\n" \
                "${vol_nums[$i]}" "${vol_pools[$i]}" "${vol_sizes[$i]}" "${vol_pcts[$i]}" "${vol_statuses[$i]}"
        done
    fi
}

get_volume_info

echo ""
