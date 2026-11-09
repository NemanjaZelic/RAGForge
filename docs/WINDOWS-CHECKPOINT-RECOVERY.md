# Windows checkpoint sharing recovery

A completed 3GPP evaluator's supervisor stopped while replacing `status.json`
with WinError 5. Its existing RFC child continued computing and retained every
committed result. This was a status-publication failure, not a retrieval error.
The original failed status, traceback, frozen runtime and all inputs are retained.

`atomic_json` now retries Windows access/share/lock errors 5, 32 and 33 for at
most eight replace attempts. It reuses the same complete fsynced temporary file;
the total backoff is bounded at 1.05 seconds. Other permission errors propagate
immediately. Persistent errors still fail and preserve the prior checkpoint,
with the owned temporary file cleaned up. There is no permission change or
antivirus bypass. File content and successful publication semantics are unchanged.

Tests exercise each transient Windows code, permanent denial, unrelated permission
failure, and a real Windows reader handle opened without delete sharing. Closing
that handle during the first backoff allows the actual rename to succeed.

Operational recovery uses a separate one-shot watcher with Windows
`FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE` reads. It follows the
already running RFC process and never reruns completed inference. The active-run
pointer identifies its separate recovery status; the failed supervisor's status
is preserved as history. Once both 240-call RFC comparisons complete, the watcher
verifies counts/errors and privately saves the consolidated numerical report.
No frozen evaluator or active model/index is patched.

Completed computation remains separate from passing evidence quality. The source
reviews remain Kernel MM113/120, RFC MM117/120; 3GPP full-bank semantic review is
still open. This operational correction cannot close a quality gate.
