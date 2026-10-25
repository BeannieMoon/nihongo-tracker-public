# Audio tracker — design

## Catalogue design (agreed 2026-10-25)

Scope: drama CDs, situation CDs, tokutens, audiobooks. Not YouTube, not music, no marketplace.
A separate app in the Beannie Log style (themes, Fraunces/Source Sans, portraits, detail pages), usable
on the phone.

**Shape:** Franchise (DIABOLIK LOVERS, HypMic…, linked to its games/anime) → Series page (like a VN detail
page) → Volumes = LIs (character + CV per volume) → Tracks (scanner-filled). Tokutens attach to their
release and/or the game they came with, plus the store.

**Per volume:** listened check, from–to dates, time (scanned / real runtime), ★, rating 1–10, notes, links
(website, VGMdb, DLsite, the game).

**Filters:** audience (Otome / BL / Joseimuke / General), All-ages / R18 (demo both as its own flag and as a
filter tag), kind (Drama CD / Situation CD / Tokuten / Audiobook), status (listening / completed / planned /
paused / dropped), tags, voice actor, star.

**Adding things:** manual add (single + bulk, like the old tracker's Bulk Add Series); the scanner (files +
VGMdb/DLsite/catalogue metadata) only ever proposes: finds wait in a **Dumper** tab to accept / merge /
discard, and never overwrite manual edits. Bulk loading all owned audio waits for your go.

**Granularity (agreed):** Franchise → Series (product line) → **CD** (the unit you own, listen to, date,
star and rate; LI-per-volume series = one CD per LI) → Tracks (real durations; type drama / free talk /
song / bonus — songs don't count toward listening time). Kinds: Drama CD (situation CDs included), Tokuten,
Audiobook. Each series and CD has "Have it" (on NAS / packed / physical CD / other drive / streaming only /
wishlist) and "Where it is" (path, shelf, link). Library has tiles and a list view.

**Borrowed ideas from [dramacd-browser](https://github.com/Appealpotato/dramacd-browser)** (no licence file,
so ideas only, no code): per-store metadata sources for the scanner — Rejet works DB, Stellaworth product
pages (its 【キャスト】 block gives 役名：声優 = LI + CV), Chil-Chil (BL drama CD database), Animate, DLsite,
Pokedora, melon, Booth; tokuten ↔ game linking; collapsing the same recording in several formats / SFX vs
no-SFX variants into one track; a confirm step for matched metadata (our Dumper); and its Whisper +
synced-lyrics player as a local read-along option next to Audiobookshelf + Nagare.

**Out:** CSV/XLSX export of what you've listened to, with the old sheet's columns (Name, Level, Start,
Finished, Difficulty, Notes, Notes after finishing, Source, Time, Series, Type, Voice Actors, DB link…), and
NihongoTracker sync of listened volumes as `audio` logs on their dates.

One place for your Japanese audio: the **collection** (what exists, what you have and where), the
**diary** (what you listened to, when, notes and ratings) and **automatic time logging** into NihongoTracker.
Spoken audio only (drama CDs, voice works, audiobooks, podcasts), not music.
Listening happens on Android, in the PC browser, in Spotify and from local files.

## What a work is

| Field | Notes |
|---|---|
| kind | **Drama CD**, **Tokuten** (store/pre-order bonus CD, linked to its parent release and the store), **Voice work** (DLsite-style situation/ASMR), **Audiobook**, **Podcast** |
| age | **All ages** / **R18**, separate from kind, so "drama CD AA" and "drama CD R18" are filters, not separate kinds |
| identity | title (JP), series, catalog number, DLsite RJ/BJ, Audible ASIN, VGMdb id, Rejet catalog entry |
| metadata | VAs, label, release date, cover, **tracks with real durations**, total runtime |
| collection | status: wanted / have / ripped / incomplete; copies: where the files live (disk/NAS path via `archive.sqlite` volumes), format, tokutens included |
| diary | listening status, start, finish, level, difficulty, rating, notes, notes after finishing, relistens |

Tokutens hang off a parent work, so "Diabolik Lovers More, Blood" shows its main CDs and every store bonus
as one family, each with its own runtime and age flag.

## Metadata: real runtimes instead of guesses

Filled in order of trust, never overwriting a manual edit:
1. **Your files.** Scanning a rip folder gives exact track durations and embedded tags. These are already
   spread across catalogues: Neoromance (Corda/Angelique/Haruka), Rejet, DIABOLIK LOVERS, DRAMA CD SORT.
2. **VGMdb** for commercial drama CDs and tokutens: track list with durations, catalog number, VAs, label,
   and which store bonus came with which release.
3. **DLsite** for voice works (RJ/BJ): runtime, VAs, circle, and the age rating (all-ages vs R18 is part of
   the listing).
4. **Audible / publisher** for audiobooks (ASIN, runtime, narrator).
5. Manual entry as the last resort.

Existing indexes seed the catalogue: your current sheet (72 rows), the Rejet catalog scrape, the AS
Otome/BL Voice Index (AA vs R18 voice works with RJ codes), and the DIABOLIK LOVERS catalogue.

Once works have real runtimes, the 70 drama CD logs already sent from the sheet snapshot are **corrected
in place** on NihongoTracker (same log, new time). The ledger already stores each log's id.

## Capture, part 1: Audiobookshelf for drama CDs and audiobooks

The rips already live on the NAS (`Z:\AUDIO`), so an Audiobookshelf (ABS) server on the Synology, with that
folder mounted read-only, can serve them to the ABS Android app and the browser.
- **Exact listening time:** ABS records listening sessions per item and per day
  (`/api/me/listening-sessions`), with real seconds listened. That beats any estimate, and the nightly
  sync reads it directly.
- **Read-along:** Nagare (by the GSM author) watches ABS playback and shows a live subtitle timeline in the
  browser, with Anki mining. It runs on bpwhelan's ABS fork, which adds the playback-session endpoint Nagare
  uses. Drama CDs need subtitles for this: Whisper transcripts (ASB-Auto-Subgen, or the existing srt
  cleanup workflow) saved next to the audio.
- The ABS library layout can mirror the existing folders (`OTOME|BL / AA|R18 / Original|Tokuten`), so kind
  and age come straight from the path.
- **Needs your OK before anything is written to the NAS:** the ABS container and its config/metadata
  folder.

## Capture, part 2: ListenBrainz for everything else

Everything not played through ABS reports to ListenBrainz. It was chosen over Last.fm because listens carry the track duration
and reading your own history needs no API key.
- **Android**: Pano Scrobbler reads the system media session, so it sees YouTube, Bilibili, SoundCloud,
  Spotify (including podcasts) and local players.
- **PC browser**: Web Scrobbler extension (YouTube, SoundCloud and Bilibili connectors).
- **Spotify desktop**: ListenBrainz's Spotify link (music tracks only: Spotify doesn't expose podcast
  plays). For the past, Spotify's extended streaming history export has `ms_played` for episodes.
- **Local files**: a ListenBrainz plugin for the desktop player.

Each listen counts `min(track duration, time until the next listen)` minutes. A listen is matched to a work
by rules (album, artist, channel, URL, or track titles matching the work's track list). Anything
Japanese-looking that matches no work lands in the diary's **inbox**. Sorting it once (to a work, or "music,
ignore") creates a rule for next time.

## Where it lives

- **Store + diary page:** a Google Sheet with a small Apps Script web app on top. It's reachable on the
  phone and the PC, backup is trivial, and it serves JSON to the PC script.
- **PC side:** `nt_sync.py` (Task Scheduler, nightly) does the heavy work: scans rip folders, fetches
  VGMdb/DLsite metadata, pulls ListenBrainz, matches listens, sends daily `audio` logs
  (`audio:<day>:<work>` ids) and corrects old ones. The same nightly run handles GSM, ttu and Chimahon.
- **NihongoTracker:** each log gets kind and age as tags, so drama CD AA / R18 / tokuten / audiobook can be
  filtered there too.

## Build order

1. Catalogue core: sheet schema, import the 72 sheet rows, fill kind/age, match to VGMdb/DLsite/files for
   real runtimes, correct the 70 sent logs.
2. Diary page (Apps Script): browse/filter works by kind and age, tokuten families, edit diary fields.
3. Capture: ListenBrainz account + Pano Scrobbler + Web Scrobbler, then matching, the inbox and nightly sync.
4. Collection: link rip folders and copies from the existing catalogues and `archive.sqlite`.

## Open
- Which desktop player plays local rips?
- Where are the rips for the CDs in the sheet (which folders/discs)?
- Rejected for now: Apps Script pushing to NihongoTracker directly. Cloudflare may block Google's fetcher,
  and pushing from the PC reuses the path that already works.
