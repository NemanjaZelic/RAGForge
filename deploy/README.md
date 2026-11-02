# Operator rollout example

The systemd unit is an example for an operator-managed Linux host. It is not
installed or started by `deploy`, and it is not a claim of a tested production
host. It runs a read-only shared backend on loopback; arrange TLS termination at
the configured public resource authority, preserving Host and Authorization. A
direct non-loopback listener instead needs explicit certificate/key flags.

Prepare the runtime under `/opt/ragforge`, versioned immutable bundles and a local
deployment registry under `/var/lib/ragforge`, and public auth policy/keys under
`/etc/ragforge`. Create the service identity using your host administration
workflow. The service needs read access; keep activation/write privileges with
the operator. Generate deployment references on the target host so absolute
bundle/interpreter paths describe that host, not the build workstation.

The template has restart supervision and a 20-second stop budget around the
server's 15-second graceful shutdown. `Type=exec` confirms launching the binary;
application readiness still requires authenticated `ragforge doctor` and checking
the expected build ID. See the [systemd service](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html)
and [execution](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html)
references for host-specific review. CI checks unit syntax when systemd-analyze
is available; it does not install a service or test a remote machine.

For updates, prepare the new bundle in a separate version directory, verify it,
run `activate` with a known source smoke query, then explicitly restart the
supervisor. Existing requests keep the loaded version until restart; this is not
a zero-downtime switch. Check readiness/build ID afterwards. If the new process
fails readiness, run `rollback` with a known probe and restart again. A failed
candidate validation never changes the active pointer. No bundle is deleted.

Back up the immutable bundle directories referenced by active/previous registry
entries, `deployment.json`, the public auth policy and the compatible runtime
wheel/lockfile. Follow the host's existing protected backup workflow: SQLite
bundles include extracted document text. Keep operator TLS/issuer private keys in
their existing secret backup system. After restore, verify every bundle and
regenerate the registry for new host paths if needed; run smoke/readiness checks
before starting clients. This is a manual backup procedure, not an automated
replication/archive service.

On Windows, `serve.json` contains a reviewable argument array for the local
interpreter. Use the explicit CLI under the chosen process supervisor. No global
Windows service, scheduled task, firewall rule or host configuration is created.
