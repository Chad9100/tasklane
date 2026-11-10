import argparse
import os
import shutil
import shlex
import subprocess
import sysconfig
from pathlib import Path

import pytest

from tasklane import completion
from tasklane.cli import build_parser, main


def generate(shell: str) -> str:
    return completion.script(shell, build_parser())


def test_spec_reflects_the_real_parser():
    spec = completion.build_spec(build_parser())
    names = [c.name for c in spec.commands]
    assert names[:3] == ["add", "ls", "do"]
    assert {"archive", "due", "report", "completion"} <= set(names)
    ls = next(c for c in spec.commands if c.name == "ls")
    assert {"--all", "--hidden", "--json", "--file", "--color"} <= set(ls.options)
    assert set(spec.value_options) == {"--file", "--color", "--days", "--output"}
    assert spec.option_choices == {"--color": ["auto", "always", "never"]}
    assert spec.file_options == ["--file", "--output"]
    shells = next(c for c in spec.commands if c.name == "completion")
    assert shells.positional_choices == list(completion.SHELLS)


@pytest.mark.parametrize("shell", completion.SHELLS)
def test_every_command_and_option_is_in_every_script(shell):
    spec = completion.build_spec(build_parser())
    text = generate(shell)
    for cmd in spec.commands:
        assert cmd.name in text
        for opt in cmd.options:
            # fish writes long options as "-l name"
            assert opt in text or f"-l {opt[2:]}" in text
    assert all(value in text for value in ("auto", "always", "never"))


def test_cli_prints_script_without_touching_the_task_file(tmp_path, capsys):
    todo = tmp_path / "todo.txt"
    assert main(["--file", str(todo), "completion", "bash"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# bash completion for tasklane")
    assert "complete -F _tasklane_complete tasklane" in out
    assert not todo.exists()


def test_cli_rejects_unknown_shell(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["completion", "tcsh"])
    assert exc.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_script_rejects_unknown_shell():
    with pytest.raises(ValueError, match="unsupported shell"):
        completion.script("tcsh", build_parser())


def test_help_text_with_quotes_is_escaped():
    parser = argparse.ArgumentParser(prog="demo")
    sub = parser.add_subparsers()
    p = sub.add_parser("say", help="say 'hi' to bob's cat")
    p.add_argument("--loud", action="store_true", help="it's loud")
    assert "-d 'say \\'hi\\' to bob\\'s cat'" in completion.script("fish", parser)
    assert "-d 'it\\'s loud'" in completion.script("fish", parser)
    assert "'say' = 'say ''hi'' to bob''s cat'" in completion.script("powershell", parser)
    assert "'say:say '\\''hi'\\'' to bob'\\''s cat'" in completion.script("zsh", parser)


# -- running the scripts in real shells (skipped when a shell is missing) ------
def _bash() -> str | None:
    found = shutil.which("bash")
    if os.name == "nt":
        git_bash = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
        if found and "system32" in found.lower():  # WSL launcher, not a usable bash here
            found = None
        found = found or (str(git_bash) if git_bash.exists() else None)
    return found


BASH_CASES = {
    'tasklane ""': "add ls do undo pri depri edit rm archive due projects contexts report export completion",
    "tasklane d": "do depri due",
    "tasklane --file x.txt l": "ls",
    "tasklane --color x.txt --c": "--color",
    'tasklane --color ""': "auto always never",
    "tasklane ls --h": "--help --hidden",
    "tasklane due --days 3 --j": "--json",
    'tasklane completion ""': "bash zsh fish powershell",
    'tasklane edit 3 ""': "",
    "tasklane --file sub/no": "sub/notes.txt",
}


def test_bash_completion_runs(tmp_path):
    bash = _bash()
    if not bash:
        pytest.skip("bash not available")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "notes.txt").write_text("x\n")
    probe = [generate("bash")]
    probe.append(
        't() { COMP_WORDS=("$@"); COMP_CWORD=$((${#COMP_WORDS[@]} - 1)); COMPREPLY=(); '
        '_tasklane_complete; echo "${COMPREPLY[*]}"; }'
    )
    probe += [f"t {case}" for case in BASH_CASES]
    result = subprocess.run(
        [bash, "--norc", "--noprofile", "-s"],
        input="\n".join(probe) + "\n",
        capture_output=True,
        text=True,
        cwd=tmp_path,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == list(BASH_CASES.values())


PS_CASES = {
    "tasklane ": "add ls do undo pri depri edit rm archive due projects contexts report export completion",
    "tasklane d": "do depri due",
    "tasklane --file x.txt l": "ls",
    "tasklane --color ": "auto always never",
    "tasklane --color a": "auto always",
    "tasklane ls --h": "--help --hidden",
    "tasklane due --days 3 --j": "--json",
    "tasklane completion p": "powershell",
}


def test_powershell_completion_runs(tmp_path):
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        pytest.skip("PowerShell not available")
    script = tmp_path / "tasklane.ps1"
    script.write_text(generate("powershell"), encoding="utf-8")
    probe = [f". '{script}'"]
    for line in PS_CASES:
        probe.append(
            f"$r = TabExpansion2 -inputScript '{line}' -cursorColumn {len(line)}; "
            "(@($r.CompletionMatches | ForEach-Object CompletionText) -join ' ')"
        )
    runner = tmp_path / "probe.ps1"
    runner.write_text("\n".join(probe) + "\n", encoding="utf-8")
    result = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(runner)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == list(PS_CASES.values())


@pytest.mark.parametrize("shell, check", [("zsh", ["zsh", "-n"]), ("fish", ["fish", "--no-execute"])])
def test_zsh_and_fish_scripts_parse(tmp_path, shell, check):
    exe = shutil.which(check[0])
    if not exe:
        pytest.skip(f"{shell} not available")
    path = tmp_path / f"tasklane.{shell}"
    path.write_text(generate(shell), encoding="utf-8")
    result = subprocess.run([exe, *check[1:], str(path)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr


# -- +project and @context names from the current file ------------------------
NAMES_TODO = (
    "(A) Call mom +family @phone\n"
    "Buy milk +home @errands\n"
    "x 2026-11-01 Fix bike +home @garage\n"
    "Odd names +$(touch_pwned) @it's\n"
)


def test_spec_lists_the_commands_that_complete_names():
    assert completion.build_spec(build_parser()).name_commands == ["add", "ls", "edit"]


@pytest.mark.parametrize("shell", completion.SHELLS)
def test_parsers_without_projects_command_get_no_name_completion(shell):
    parser = argparse.ArgumentParser(prog="demo")
    sub = parser.add_subparsers()
    sub.add_parser("add").add_argument("text", nargs="+")
    text = completion.script(shell, parser)
    assert completion.build_spec(parser).name_commands == []
    assert not any(call in text for call in ("kind=contexts", "set kind contexts", "'contexts'"))


def _scripts_env(tmp_path) -> dict[str, str]:
    """Environment with the installed tasklane on PATH and a throwaway TASKLANE_FILE."""
    scripts = sysconfig.get_path("scripts")
    if not shutil.which("tasklane", path=scripts):
        pytest.skip("tasklane is not installed as a command")
    default = tmp_path / "default.txt"
    default.write_text("Default file task +fromenv @envctx\n", encoding="utf-8")
    env = dict(os.environ, TASKLANE_FILE=str(default))
    env["PATH"] = scripts + os.pathsep + env.get("PATH", "")
    return env


def test_bash_completes_names_from_the_file(tmp_path):
    bash = _bash()
    if not bash:
        pytest.skip("bash not available")
    env = _scripts_env(tmp_path)
    (tmp_path / "todo.txt").write_text(NAMES_TODO, encoding="utf-8")
    # (COMP_LINE, words as bash splits them: "@" is in COMP_WORDBREAKS) -> reply
    cases = [
        ("tasklane --file todo.txt add Call +", ["tasklane", "--file", "todo.txt", "add", "Call", "+"],
         r"+\$\(touch_pwned\) +family +home"),
        ("tasklane --file todo.txt add Call +h", ["tasklane", "--file", "todo.txt", "add", "Call", "+h"], "+home"),
        ("tasklane ls --file todo.txt @", ["tasklane", "ls", "--file", "todo.txt", "@"],
         r"@errands @garage @it\'s @phone"),
        ("tasklane --file todo.txt edit 2 Buy @ph", ["tasklane", "--file", "todo.txt", "edit", "2", "Buy", "@", "ph"],
         "phone"),
        ("tasklane add x +", ["tasklane", "add", "x", "+"], "+fromenv"),
        ("tasklane --file todo.txt do +", ["tasklane", "--file", "todo.txt", "do", "+"], ""),
        ("tasklane --file todo.txt ls --a", ["tasklane", "--file", "todo.txt", "ls", "--a"], "--all"),
    ]
    probe = [generate("bash")]
    probe.append(
        't() { COMP_LINE="$1"; COMP_POINT=${#COMP_LINE}; shift; COMP_WORDS=("$@"); '
        'COMP_CWORD=$((${#COMP_WORDS[@]} - 1)); COMPREPLY=(); _tasklane_complete; echo "${COMPREPLY[*]}"; }'
    )
    for line, words, _ in cases:
        probe.append("t " + " ".join(shlex.quote(w) for w in [line, *words]))
    result = subprocess.run(
        [bash, "--norc", "--noprofile", "-s"],
        input="\n".join(probe) + "\n",
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=env,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [expected for _, _, expected in cases]
    assert not (tmp_path / "touch_pwned").exists()
    assert (tmp_path / "todo.txt").read_text(encoding="utf-8") == NAMES_TODO


def test_powershell_completes_names_from_the_file(tmp_path):
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        pytest.skip("PowerShell not available")
    env = _scripts_env(tmp_path)
    todo = tmp_path / "todo.txt"
    todo.write_text(NAMES_TODO, encoding="utf-8")
    cases = {
        f"tasklane --file '{todo}' add Call +": "'+$(touch_pwned)' +family +home",
        f"tasklane --file '{todo}' add Call +h": "+home",
        f"tasklane ls --file '{todo}' @": "'@errands' '@garage' '@it''s' '@phone'",
        f"tasklane --file '{todo}' edit 2 Buy '@ph": "'@phone'",
        "tasklane add x +": "+fromenv",
        f"tasklane --file '{todo}' do +": "",
    }
    script = tmp_path / "tasklane.ps1"
    script.write_text(generate("powershell"), encoding="utf-8")
    probe = [f". '{script}'"]
    for line in cases:
        quoted = line.replace("'", "''")
        probe.append(
            f"$r = TabExpansion2 -inputScript '{quoted}' -cursorColumn {len(line)}; "
            "(@($r.CompletionMatches | ForEach-Object CompletionText) -join ' ')"
        )
    runner = tmp_path / "probe.ps1"
    runner.write_text("\n".join(probe) + "\n", encoding="utf-8")
    result = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(runner)],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == list(cases.values())
    assert todo.read_text(encoding="utf-8") == NAMES_TODO


def test_fish_completes_names_from_the_file(tmp_path):
    fish = shutil.which("fish")
    if not fish:
        pytest.skip("fish not available")
    env = _scripts_env(tmp_path)
    todo = tmp_path / "todo.txt"
    todo.write_text(NAMES_TODO, encoding="utf-8")
    script = tmp_path / "tasklane.fish"
    script.write_text(generate("fish"), encoding="utf-8")
    lines = [
        f"tasklane --file {todo} add Call +h",
        f"tasklane ls --file {todo} @",
        "tasklane add x +",
        f"tasklane --file {todo} do +",
    ]
    probe = [f"source {shlex.quote(str(script))}"]
    probe += [f"echo (complete -C {shlex.quote(line)} | string replace -r '\t.*' '')" for line in lines]
    result = subprocess.run(
        [fish, "--no-config", "-c", "; ".join(probe)],
        capture_output=True, text=True, env=env, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "+home",
        "@errands @garage @it's @phone",  # fish escapes a completion only when inserting it
        "+fromenv",
        "",
    ]
