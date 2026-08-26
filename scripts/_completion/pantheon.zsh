#compdef pantheon pantheon-backup pantheon-calendar pantheon-contacts pantheon-cookbook pantheon-docs pantheon-gallery pantheon-mail pantheon-mcp pantheon-memory pantheon-notes pantheon-personal pantheon-preset pantheon-research pantheon-sessions pantheon-signature pantheon-skills pantheon-tasks pantheon-theme pantheon-webhook
# Zsh tab-completion for the pantheon umbrella + sub-CLIs.
#
# Drop in any directory on $fpath, e.g.:
#     fpath=(/path/to/pantheon-ui/scripts/_completion $fpath)
#     autoload -U compinit; compinit
#
# Then `pantheon <tab>` completes subcommands; `pantheon mail <tab>`
# completes mail subcommands; `pantheon-mail <tab>` works the same.

_pantheon_scripts_dir() {
    local self="${(%):-%x}"
    while [[ -L "$self" ]]; do self="$(readlink "$self")"; done
    cd "${self:h}/.." && pwd
}

typeset -gA _pantheon_subs

_pantheon_refresh() {
    _pantheon_subs=()
    local dir="$(_pantheon_scripts_dir)"
    local py="$dir/../venv/bin/python"
    [[ -x "$py" ]] || py="$(command -v python3)"
    local f sub help_out commands
    for f in "$dir"/pantheon-*; do
        [[ -x "$f" ]] || continue
        case "$f" in
            *.bak|*.pyc|*.pre-*) continue ;;
        esac
        sub="${${f:t}#pantheon-}"
        help_out=$("$py" "$f" --help 2>/dev/null) || continue
        commands=$(echo "$help_out" | grep -oE '\{[a-z0-9_,-]+\}' | head -1 \
            | tr -d '{}' | tr ',' ' ')
        _pantheon_subs[$sub]="$commands"
    done
}

_pantheon() {
    [[ ${#_pantheon_subs} -eq 0 ]] && _pantheon_refresh

    local cmd="${words[1]}"

    if [[ "$cmd" == "pantheon" ]]; then
        if (( CURRENT == 2 )); then
            local -a subs=(${(k)_pantheon_subs} help)
            _describe 'subcommand' subs
            return
        fi
        local sub="${words[2]}"
        if [[ "$sub" == "help" ]] && (( CURRENT == 3 )); then
            local -a subs=(${(k)_pantheon_subs})
            _describe 'subcommand' subs
            return
        fi
        if (( CURRENT == 3 )); then
            local -a sc=(${(s/ /)_pantheon_subs[$sub]})
            _describe 'command' sc
            return
        fi
        return
    fi

    # pantheon-foo <tab>
    local sub="${cmd#pantheon-}"
    if (( CURRENT == 2 )); then
        local -a sc=(${(s/ /)_pantheon_subs[$sub]})
        _describe 'command' sc
        return
    fi
}

_pantheon "$@"
