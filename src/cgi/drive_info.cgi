#!/bin/sh
printf "Content-Type: text/plain; charset=utf-8\r\n\r\n"
exec /var/packages/drive_info/target/scripts/drive_number.sh 2>&1
