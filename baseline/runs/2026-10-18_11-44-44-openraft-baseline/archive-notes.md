# Git archive packaging

The original reports, receipts and change manifests are unchanged.

The retained log `turns/0001/changes/files/tests/_log/ut.2026-10-18-03` is 6,409,095,708 bytes and exceeds GitHub's per-file limit. Its exact contents are archived as a gzip stream split into 5 parts of at most 48 MiB. The original log and unsplit gzip remain local and are excluded from Git.

From this run directory, reconstruct the log without changing retained evidence:

```sh
cat turns/0001/changes/files/tests/_log/ut.2026-10-18-03.gz.part* | gzip -dc > /tmp/openraft-ut.2026-10-18-03
```

Generated compiler caches and Java `.class` files are excluded. Source files, dependency lockfiles, reports, execution output and research logs are retained, including evidence otherwise ignored by copied target `.gitignore` files.
