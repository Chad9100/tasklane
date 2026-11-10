import argparse
import os
import shutil
import subprocess
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
    assert set(spec.value_options) == {"--file", "--color", "--days"}
    assert spec.option_choices == {"--color": ["auto", "always", "never"]}
    assert spec.file_options == ["--file"]
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
    'tasklane ""': "add ls do undo pri depri edit rm archive due projects contexts report completion",
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
    "tasklane ": "add ls do undo pri depri edit rm archive due projects contexts report completion",
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
