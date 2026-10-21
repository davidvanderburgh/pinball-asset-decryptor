#!/bin/bash
# Give a root-login WSL distro an ordinary user, the way Ubuntu's own first
# run would have (PAD-661).
#
# install_prerequisites.ps1 installs Ubuntu with `wsl --install --no-launch`,
# which never runs Ubuntu's first-boot setup (/usr/lib/wsl/wsl-setup, the
# "Create a default Unix user account" prompt).  The distro it leaves behind
# has no user at all and logs in as root, and as root the emulator's game
# window stays black (PAD-659).  This is that setup, without the prompt:
#
#   * a user who already exists (uid >= 1000 with a login shell) is adopted,
#     exactly as wsl-setup adopts one - a person's own account is never
#     replaced by ours;
#   * otherwise one is made, named after the Windows user the way wsl-setup
#     names it, in the groups wsl-setup gives it;
#   * it becomes the default in /etc/wsl.conf, with wsl-setup's own rule: an
#     existing [user] default= is somebody's choice and is left alone.
#
# The account has no password (nobody is here to type one), so sudo is
# granted without one.  That gives away nothing: every Windows user can
# already be root in this distro with `wsl -u root`.  And because the user
# exists, a later first launch of Ubuntu from the Start menu finds it and
# finishes quietly instead of asking for another.
#
# Usage (as root):  wsl_default_user.sh <windows-user-name>
# Last line out:    PADUSER=<name> <uid>      (the installer reads it)
set -eu

DEFAULT_GROUPS="adm cdrom sudo dip plugdev"
WSL_CONF=${PAD_WSL_CONF:-/etc/wsl.conf}
SUDOERS_D=${PAD_SUDOERS_D:-/etc/sudoers.d}

[ "$(id -u)" = 0 ] || { echo "must run as root" >&2; exit 2; }

# wsl-setup's own get_first_interactive_uid.
first_user() {
    getent passwd | grep -Ev '/nologin|/false|/sync' |
        sort -t: -k3,3n | awk -F: '$3 >= 1000 && $3 < 60000 { print $1; exit }'
}

# wsl-setup's own name rule: lower case, spaces to _, then only [a-z0-9_-],
# starting with a letter or _.
pick_name() {
    local n
    n=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr ' ' '_' |
        sed 's/[^a-z0-9_-]//g; s/^[^a-z_]*//' | cut -c1-32)
    # A name the system already uses (root, daemon, games...) is not free.
    if [ -z "$n" ] || getent passwd "$n" >/dev/null; then
        n=pad
    fi
    printf '%s' "$n"
}

user=$(first_user)
if [ -z "$user" ]; then
    user=$(pick_name "${1:-}")
    if getent passwd "$user" >/dev/null; then
        echo "no free name for the new user ($user is taken)" >&2
        exit 3
    fi
    adduser --quiet --disabled-password --gecos '' "$user"
    for g in $DEFAULT_GROUPS; do
        getent group "$g" >/dev/null && usermod -aG "$g" "$user"
    done
    rule=$SUDOERS_D/90-pad-$user
    printf '%s ALL=(ALL) NOPASSWD:ALL\n' "$user" > "$rule.tmp"
    chmod 0440 "$rule.tmp"
    if command -v visudo >/dev/null && ! visudo -cf "$rule.tmp" >/dev/null; then
        rm -f "$rule.tmp"
    else
        mv "$rule.tmp" "$rule"
    fi
    echo "made the user $user"
else
    echo "found the user $user"
fi

# wsl-setup's set_user_as_default.
touch "$WSL_CONF"
if ! grep -q '^\[user\]' "$WSL_CONF"; then
    printf '\n[user]\ndefault=%s\n' "$user" >> "$WSL_CONF"
elif ! sed -n '/^\[user\]/,/^\[/{/^\s*default\s*=/p}' "$WSL_CONF" | grep -q .; then
    sed -i '/^\[user\]/a\default='"$user" "$WSL_CONF"
fi

echo "PADUSER=$user $(id -u "$user")"
