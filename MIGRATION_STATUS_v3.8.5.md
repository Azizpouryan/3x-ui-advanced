# v3.8.5 migration status — NOT READY

Date: 2026-10-24

## Current result

The work is isolated on branch `upgrade/v3.8.5-preserve-admin`. The default `main` branch has not been changed, and no custom release has been published.

Latest full validation run:
- Workflow: https://github.com/Azizpouryan/3x-ui-advanced/actions/runs/40032260681
- Frontend dependency resolution: passed
- Frontend production build: passed
- `bash -n` on `install.sh`, `update.sh`, `x-ui.sh`, and `install_offline.sh`: passed
- `go test ./...`: failed
- Linux binary build, packaged release, and refreshed offline bundle: skipped because Go tests failed

## Blocking findings

The file-level three-way merge is not a reliable integration method for this repository. It combined current-fork backend files with incompatible v3.8.5 models and APIs. The latest Go test run reports, among other issues:

- AmneziaWG/TUIC code expects model and client fields that the merged model does not define.
- WireGuard model tests reference fields and helpers missing from the merged model.
- Settings validation tests expect `SmtpFrom` and `IpLimitAllowlist` fields that are missing from the merged settings entity.
- Xray tests reference helper functions and `HotDiff` fields absent from the merged implementation.
- The custom database migration references model types that aren't present in the merged tree.
- The production HTTP server test detects direct `Serve` calls in `internal/sub/sub.go` and `internal/web/web.go`, rather than routing them through `network.ServeHTTP`.

These are structural source-integration failures. They must be resolved by starting from the complete official v3.8.5 tree and deliberately porting RBAC/admin changes onto it, rather than continuing to auto-merge hundreds of unrelated files.

## Installer safety

The candidate's `install.sh` points at this repository's releases. Its default/latest path now refuses to install unless release `v3.8.5-advanced.1` exists, so it cannot accidentally install an older `latest` release while this candidate is unvalidated. An explicit version argument still tries to download that exact release.

Do not install this branch on a production server. There is no validated v3.8.5 custom release yet.
