"""Confirmed manual command dispatch; does not observe the trial process."""
from dataclasses import dataclass
import base64

from ..terminal import DispatchState, TerminalLauncher, project_path, _terminal_argv


@dataclass(frozen=True)
class CommandRequest:
    title: str
    project: str
    command: str


def command_request(trial):
    directory = project_path(trial["directory"])
    if not isinstance(trial["command"], str) or not trial["command"].strip() or "\x00" in trial["command"]:
        raise ValueError("请填写有效的 PowerShell 命令")
    return CommandRequest(trial["name"], directory, trial["command"])


def command_argv(config, request):
    project = project_path(request.project)
    literal = "'" + project.replace("'", "''") + "'"
    # The user command is deliberately executed only after explicit confirmation.
    # Encoding keeps its syntax separate from directory and Terminal argument syntax.
    encoded = base64.b64encode(request.command.encode("utf-8")).decode("ascii")
    script = ("Set-Location -LiteralPath " + literal + " -ErrorAction Stop; "
              "& ([scriptblock]::Create([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + encoded + "'))))")
    return _terminal_argv(config, project, script, "个人试验盒 · " + request.title)


class ExperimentLauncher(TerminalLauncher):
    def launch(self, request: CommandRequest):
        if self.state.pending:
            return False
        try:
            if not isinstance(request, CommandRequest):
                raise ValueError("无效的试验启动请求")
            project_path(request.project)
            if not request.command.strip() or "\x00" in request.command:
                raise ValueError("请填写有效的 PowerShell 命令")
        except ValueError as error:
            self._emit(DispatchState(error=str(error)))
            return False
        return self._dispatch(request)
