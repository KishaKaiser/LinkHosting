#!/bin/bash
# entrypoint.sh — create SFTP users from /data/sftp/users.conf and start sshd
set -e

USERS_FILE="/data/sftp/users.conf"

if [ -f "$USERS_FILE" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        # Skip comments and blank lines
        [[ "$line" =~ ^# ]] && continue
        [[ -z "$line" ]] && continue

        # Format: username:password:::homedir
        IFS=':' read -r username password _ _ homedir <<< "$line"
        [ -z "$username" ] && continue

        # Create user if not exists
        if ! id "$username" &>/dev/null; then
            useradd -M -s /usr/sbin/nologin -G sftpusers "$username"
        fi
        echo "${username}:${password}" | chpasswd

        # Set up chroot directory (must be owned by root)
        chroot_dir="/data/sftp/${username}"
        mkdir -p "${chroot_dir}/www"
        chown root:root "${chroot_dir}"
        chmod 755 "${chroot_dir}"
        chown "${username}:sftpusers" "${chroot_dir}/www"
        chmod 775 "${chroot_dir}/www"

    done < "$USERS_FILE"
fi

exec /usr/sbin/sshd -D -e
