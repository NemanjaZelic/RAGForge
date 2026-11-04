# Background corpus runs on Windows

Use the one-shot native launcher when a long benchmark must continue independently
of the terminal that started it. It creates no Windows service, recurring task,
logon trigger or global power setting. It preserves the existing run configurations,
source/model pins, committed checkpoints and storage budgets.

The previous hidden subprocess launch still belonged to the terminal's process
lifetime. Windows can terminate a job's member processes together. The new launcher
uses the local WMI provider; Microsoft documents its process creation separately
from child-process job inheritance. See [Windows job objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
and [process startup options](https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-processstartup).

These commands require the project's already prepared `execution-v1` scale run
and/or `quality-v1/full-rfc-rebuild-v1` follow-up. They do not create corpora or
change a recipe. Preview validates frozen runtime hashes and paths and starts no
process or network activity:

```powershell
.\scripts\start_background_benchmarks.ps1 -Jobs both -PublishPrivate -CheckOnly
.\scripts\start_background_benchmarks.ps1 -Jobs both -PublishPrivate
```

Choose `-Jobs scale` or `-Jobs rfc-rebuild` for one run. The launcher refuses to
start a selected benchmark when its controller is already active. The supervisor
also uses an OS writer lock; the benchmark builders retain their existing locks.

`-PublishPrivate` explicitly enables the scale run's existing numerical publisher.
The quality follow-up keeps the publication choice in its frozen configuration.
The publisher checks the expected private repository and uploads whitelisted
aggregates. Source documents, models, questions, returned text and credentials are
not published. Retrieval and model inference retain their offline guards.

Local receipts, heartbeat/exit codes and stdout/stderr logs are under
`.cache/background-benchmarks-v1/`. A current heartbeat plus a live matching PID
shows that a job is active; a stale `state: running` by itself does not. The
launcher receipt identifies the native launcher and WMI broker. PID reuse must be
checked against the command before stopping a process.

Background CPU priority is BelowNormal; the frozen model thread counts are
unchanged. A process-scoped Windows activity request is held while the supervisor's
children run and released on exit. Logging off, rebooting or external process
termination can still stop a run; resume reuses its committed checkpoints.
This is a local background execution helper, not a remote deployment or an
independent quality approval.
