"""Shell completion scripts for bash, zsh, fish and PowerShell.

The scripts are generated from the argparse parser, so every command and
option the CLI accepts is offered and new ones appear automatically. They are
static: they complete commands, options, option values with fixed choices and
paths for ``--file``, without running tasklane on every key press.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field

SHELLS = ("bash", "zsh", "fish", "powershell")


@dataclass
class Command:
    name: str
    help: str
    options: list[str] = field(default_factory=list)
    positional_choices: list[str] = field(default_factory=list)


@dataclass
class Spec:
    prog: str
    global_options: list[str]
    commands: list[Command]
    value_options: list[str]  # options that consume the next word
    option_choices: dict[str, list[str]]
    option_help: dict[str, str]
    file_options: list[str]


def _option_actions(parser: argparse.ArgumentParser):
    return [a for a in parser._actions if a.option_strings]


def build_spec(parser: argparse.ArgumentParser) -> Spec:
    value_options: list[str] = []
    choices: dict[str, list[str]] = {}
    helps: dict[str, str] = {}
    files: list[str] = []

    def note(action: argparse.Action) -> list[str]:
        names = [s for s in action.option_strings if s.startswith("--")] or list(action.option_strings)
        for name in names:
            if action.help and action.help is not argparse.SUPPRESS:
                helps.setdefault(name, action.help.replace("%(prog)s", parser.prog).replace("%%", "%"))
            if action.nargs != 0 and name not in value_options:
                value_options.append(name)
                if action.choices:
                    choices[name] = [str(c) for c in action.choices]
                elif action.metavar == "PATH":
                    files.append(name)
        return names

    global_options = [n for a in _option_actions(parser) for n in note(a)]
    commands: list[Command] = []
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        helps_by_name = {c.dest: c.help or "" for c in action._choices_actions}
        for name, sub in action.choices.items():
            cmd = Command(name, helps_by_name.get(name, ""))
            cmd.options = [n for a in _option_actions(sub) for n in note(a)]
            positionals = [a for a in sub._actions if not a.option_strings]
            if positionals and positionals[0].choices:
                cmd.positional_choices = [str(c) for c in positionals[0].choices]
            commands.append(cmd)
    return Spec(parser.prog, global_options, commands, value_options, choices, helps, files)


# -- bash --------------------------------------------------------------------
def _bash(spec: Spec) -> str:
    fn = f"_{spec.prog}_complete"
    value_pattern = "|".join(spec.value_options) or "--"
    lines = [
        f"# bash completion for {spec.prog}",
        f'# Load it with:  eval "$({spec.prog} completion bash)"',
        f"{fn}() {{",
        '    local cur="${COMP_WORDS[COMP_CWORD]}" prev="${COMP_WORDS[COMP_CWORD-1]}"',
        '    local cmd="" words="" i',
        "    for ((i = 1; i < COMP_CWORD; i++)); do",
        '        case "${COMP_WORDS[i]}" in',
        f"            {value_pattern}) ((i++)) ;;",
        "            -*) ;;",
        '            *) cmd="${COMP_WORDS[i]}"; break ;;',
        "        esac",
        "    done",
        '    case "$prev" in',
    ]
    for opt in spec.value_options:
        if opt in spec.file_options:
            action = 'COMPREPLY=($(compgen -f -- "$cur")); compopt -o filenames 2>/dev/null'
        elif opt in spec.option_choices:
            action = f'COMPREPLY=($(compgen -W "{" ".join(spec.option_choices[opt])}" -- "$cur"))'
        else:
            action = "COMPREPLY=()"
        lines.append(f"        {opt}) {action}; return 0 ;;")
    lines += [
        "    esac",
        '    case "$cmd" in',
        f'        "") if [[ "$cur" == -* ]]; then words="{" ".join(spec.global_options)}"; '
        f'else words="{" ".join(c.name for c in spec.commands)}"; fi ;;',
    ]
    for cmd in spec.commands:
        opts = " ".join(cmd.options)
        if cmd.positional_choices:
            pos = " ".join(cmd.positional_choices)
            lines.append(
                f'        {cmd.name}) if [[ "$cur" == -* ]]; then words="{opts}"; else words="{pos}"; fi ;;'
            )
        else:
            lines.append(f'        {cmd.name}) if [[ "$cur" == -* ]]; then words="{opts}"; fi ;;')
    lines += [
        "    esac",
        '    COMPREPLY=($(compgen -W "$words" -- "$cur"))',
        "}",
        f"complete -F {fn} {spec.prog}",
        "",
    ]
    return "\n".join(lines)


# -- zsh ---------------------------------------------------------------------
def _zsh_quote(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


def _zsh(spec: Spec) -> str:
    fn = f"_{spec.prog}"
    value_pattern = "|".join(spec.value_options) or "--"
    lines = [
        f"#compdef {spec.prog}",
        f"# zsh completion for {spec.prog}",
        f'# Load it with:  eval "$({spec.prog} completion zsh)"   (after compinit)',
        f"# or save it as {fn} in a directory on your $fpath.",
        f"{fn}() {{",
        "    local prev=${words[CURRENT-1]} cmd= i",
        "    for ((i = 2; i < CURRENT; i++)); do",
        "        case ${words[i]} in",
        f"            ({value_pattern}) ((i++)) ;;",
        "            (-*) ;;",
        "            (*) cmd=${words[i]}; break ;;",
        "        esac",
        "    done",
        "    case $prev in",
    ]
    for opt in spec.value_options:
        if opt in spec.file_options:
            action = "_files"
        elif opt in spec.option_choices:
            action = "compadd -- " + " ".join(spec.option_choices[opt])
        else:
            action = ":"
        lines.append(f"        ({opt}) {action}; return ;;")
    lines += ["    esac", "    if [[ -z $cmd ]]; then", "        if [[ ${words[CURRENT]} == -* ]]; then"]
    lines.append("            compadd -- " + " ".join(spec.global_options))
    lines += ["        else", "            local -a commands=("]
    for cmd in spec.commands:
        lines.append("                " + _zsh_quote(f"{cmd.name}:{cmd.help}"))
    lines += [
        "            )",
        "            _describe command commands",
        "        fi",
        "        return",
        "    fi",
        "    case $cmd in",
    ]
    for cmd in spec.commands:
        opts = " ".join(cmd.options)
        if cmd.positional_choices:
            pos = " ".join(cmd.positional_choices)
            body = f"if [[ ${{words[CURRENT]}} == -* ]]; then compadd -- {opts}; else compadd -- {pos}; fi"
        else:
            body = f"[[ ${{words[CURRENT]}} == -* ]] && compadd -- {opts}"
        lines.append(f"        ({cmd.name}) {body} ;;")
    lines += [
        "    esac",
        "}",
        'if [[ $zsh_eval_context[-1] == loadautofunc ]]; then',
        f'    {fn} "$@"',
        "else",
        f"    compdef {fn} {spec.prog}",
        "fi",
        "",
    ]
    return "\n".join(lines)


# -- fish --------------------------------------------------------------------
def _fish_quote(text: str) -> str:
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _fish_option(spec: Spec, prefix: str, opt: str) -> str:
    line = f"{prefix} -l {opt[2:]}" if opt.startswith("--") else f"{prefix} -s {opt.lstrip('-')}"
    if opt in spec.file_options:
        line += " -r -F"
    elif opt in spec.option_choices:
        line += " -x -a " + _fish_quote(" ".join(spec.option_choices[opt]))
    elif opt in spec.value_options:
        line += " -x"
    if opt in spec.option_help:
        line += " -d " + _fish_quote(spec.option_help[opt])
    return line


def _fish(spec: Spec) -> str:
    c = f"complete -c {spec.prog}"
    names = " ".join(cmd.name for cmd in spec.commands)
    lines = [
        f"# fish completion for {spec.prog}",
        f"# Load it with:  {spec.prog} completion fish | source",
        f"# or save it as ~/.config/fish/completions/{spec.prog}.fish",
        f"{c} -f",
    ]
    top = f"{c} -n 'not __fish_seen_subcommand_from {names}'"
    for opt in spec.global_options:
        lines.append(_fish_option(spec, top, opt))
    for cmd in spec.commands:
        lines.append(f"{top} -a {cmd.name} -d {_fish_quote(cmd.help)}")
    for cmd in spec.commands:
        cond = f"{c} -n '__fish_seen_subcommand_from {cmd.name}'"
        for opt in cmd.options:
            lines.append(_fish_option(spec, cond, opt))
        if cmd.positional_choices:
            lines.append(f"{cond} -a {_fish_quote(' '.join(cmd.positional_choices))}")
    lines.append("")
    return "\n".join(lines)


# -- PowerShell --------------------------------------------------------------
def _ps_quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _ps_list(items) -> str:
    return "@(" + ", ".join(_ps_quote(i) for i in items) + ")"


def _powershell(spec: Spec) -> str:
    lines = [
        f"# PowerShell completion for {spec.prog}",
        f"# Load it with:  {spec.prog} completion powershell | Out-String | Invoke-Expression",
        f"Register-ArgumentCompleter -Native -CommandName {_ps_quote(spec.prog)}, "
        f"{_ps_quote(spec.prog + '.exe')} -ScriptBlock {{",
        "    param($wordToComplete, $commandAst, $cursorPosition)",
        "    $commands = [ordered]@{",
    ]
    for cmd in spec.commands:
        lines.append(f"        {_ps_quote(cmd.name)} = {_ps_quote(cmd.help or cmd.name)}")
    lines += ["    }", "    $options = @{", f"        '' = {_ps_list(spec.global_options)}"]
    for cmd in spec.commands:
        lines.append(f"        {_ps_quote(cmd.name)} = {_ps_list(cmd.options)}")
    lines += ["    }", "    $positional = @{"]
    for cmd in spec.commands:
        if cmd.positional_choices:
            lines.append(f"        {_ps_quote(cmd.name)} = {_ps_list(cmd.positional_choices)}")
    lines += ["    }", "    $choices = @{"]
    for opt, values in spec.option_choices.items():
        lines.append(f"        {_ps_quote(opt)} = {_ps_list(values)}")
    lines += [
        "    }",
        f"    $valueOptions = {_ps_list(spec.value_options)}",
        f"    $fileOptions = {_ps_list(spec.file_options)}",
        "    $words = @($commandAst.CommandElements |",
        "        Where-Object { $_.Extent.EndOffset -le $cursorPosition } |",
        "        ForEach-Object { $_.Extent.Text })",
        "    if ($wordToComplete -ne '' -and $words.Count -gt 1) {",
        "        $words = @($words | Select-Object -First ($words.Count - 1))",
        "    }",
        "    $prev = $words[-1]",
        "    $cmd = ''",
        "    for ($i = 1; $i -lt $words.Count; $i++) {",
        "        $w = $words[$i]",
        "        if ($valueOptions -contains $w) { $i++ }",
        "        elseif (-not $w.StartsWith('-')) { $cmd = $w; break }",
        "    }",
        "    $candidates = @()",
        "    if ($fileOptions -contains $prev) { return }  # fall back to path completion",
        "    elseif ($choices.ContainsKey($prev)) { $candidates = $choices[$prev] }",
        "    elseif ($valueOptions -contains $prev) { $candidates = @() }",
        "    elseif ($wordToComplete.StartsWith('-')) {",
        "        if ($options.ContainsKey($cmd)) { $candidates = $options[$cmd] }",
        "    }",
        "    elseif ($cmd -eq '') { $candidates = @($commands.Keys) }",
        "    elseif ($positional.ContainsKey($cmd)) { $candidates = $positional[$cmd] }",
        "    $results = @($candidates | Where-Object { $_ -like \"$wordToComplete*\" } | ForEach-Object {",
        "        $tip = if ($cmd -eq '' -and $commands.Contains($_)) { $commands[$_] } else { $_ }",
        "        [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $tip)",
        "    })",
        "    $results",
        "}",
        "",
    ]
    return "\n".join(lines)


GENERATORS = {"bash": _bash, "zsh": _zsh, "fish": _fish, "powershell": _powershell}


def script(shell: str, parser: argparse.ArgumentParser) -> str:
    try:
        generator = GENERATORS[shell]
    except KeyError:
        raise ValueError(f"unsupported shell {shell!r}; choose from {', '.join(SHELLS)}") from None
    return generator(build_spec(parser))
