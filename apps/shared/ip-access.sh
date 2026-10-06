ip_access_validate_file() {
    input_file=$1
    output_file=$2
    if [ ! -r "$input_file" ] || ! awk '
        {
            sub(/\r$/, "")
            if ($0 ~ /^[ \t]*$/) next
            if ($0 !~ /^[0-9.\/]+$/) exit 1
            parts = split($0, address, "/")
            if (parts > 2 || (parts == 2 && (address[2] !~ /^[0-9]+$/ || address[2] + 0 > 32))) exit 1
            count = split(address[1], octets, "[.]")
            if (count != 4) exit 1
            for (octet_index = 1; octet_index <= 4; octet_index++) {
                if (octets[octet_index] !~ /^[0-9]+$/ || octets[octet_index] + 0 > 255) exit 1
            }
            cidr = (octets[1] + 0) "." (octets[2] + 0) "." (octets[3] + 0) "." (octets[4] + 0)
            if (parts == 2) cidr = cidr "/" (address[2] + 0)
            print cidr
            found = 1
        }
        END { if (!found) exit 1 }
    ' "$input_file" > "$output_file"; then
        printf 'Invalid or missing IPv4 CIDR list: %s\n' "$input_file" >&2
        return 1
    fi
}