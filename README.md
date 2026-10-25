# nihongo-tracker

> Public copy: code and docs only. Keys, listening logs, catalogues and covers are not included —
> put your own keys in `nihongotracker.key` / `jiten.key` and build your own catalogue with the tools.

Getting all Japanese immersion into [NihongoTracker](https://nihongotracker.app) — old history first, then ongoing sync.

`nt_sync.py` reads each source, writes a preview CSV to `out/`, and with `--push` sends logs through the
NihongoTracker API (`POST /logs/import`). Every log carries a stable external id and is recorded in
`sent.json`, so re-running never double-logs. Days are logged at noon local time; the current day is
never sent until it's over.

## Setup

1. https://nihongotracker.app/settings → API keys → Generate.
2. Save the key (only the key, one line) to `nihongotracker.key` in this folder.
3. `python nt_sync.py check`

## Sources

| Source | How |
|---|---|
| GSM (VNs/games) | `D:\Tools\GSM Data\gsm.db` daily rollups; finished titles use jiten.moe char counts spread over GSM's daily proportions |
| Hoshi Reader / Chimahon novels | ッツ sync files, Google Drive `ttu-reader-data/<book>/statistics_1_6_*.json` → `imports/ttu/` |
| Chimahon manga + novels | backup `.tachibk` → `imports/chimahon/`; per-day OCR stats (`backupMangaStats`), novel stats share ttu ids |
| LearnNatively | public library API; finished items on their finish date, manga volumes with jiten per-volume chars; 2024-07-14 (import day) → unknown date |
| Drama CDs | snapshot of the Google Sheet in `imports/dramacd_sheet.json` (temporary) |
| jiten.moe | every deck marked Completed (`jiten.key`); duplicates of other sources skipped (`jiten_map.json`, GSM deck ids); each title spread from its jiten start to finish date in your GSM rhythm (real GSM day sizes, run/gap lengths, reading speed for time), seeded so re-runs pick the same days |
| YouTube | Google Takeout `watch-history.html` → `imports/youtube/`; videos from channels that ever show kana are probed (watch page: length, category, auto-caption language, cached in `youtube_cache.json`); Japanese-spoken non-music videos become one `video` log per channel per day (mediaId = channel id), full length once per video per day; overrides in `youtube_map.json` |
| Spotify / other audio | proper audio tracker (see AUDIO_TRACKER.md) |

Hand-editable match files: `media_map.json` (GSM/ttu titles), `natively_map.json` (per Natively item),
`chimahon_map.json` (Chimahon manga id → title, written on first run). Edit and the next run uses them;
logs already sent aren't changed.

## Notes

- `/logs/import` is the Manabe (Discord) importer and needs a Discord link, so logs go one by one
  through `POST /logs` with the external id as `Idempotency-Key`.
