# Deploying the Audio Diary page

The Sheet already exists in your Drive: **Audio Diary**
(https://docs.google.com/spreadsheets/d/<your sheet id>/edit).

1. Open the Sheet → **Extensions → Apps Script**.
2. Replace everything in `Code.gs` with the contents of `apps_script/Code.gs`.
3. **+ (Add a file) → HTML**, name it exactly `Index`, and paste the contents of `apps_script/Index.html`.
4. Save (Ctrl+S). In the function dropdown at the top pick **setup** → **Run**. Google asks to authorise
   access to your own Sheet once: Review permissions → your account → Advanced → Go to (unsafe) → Allow.
   (It says "unsafe" only because the script is yours and not published by a verified company.)
5. **View → Logs** (or the Execution log below the code) shows `API token for tools/diary_api.py: …`.
6. **Deploy → New deployment** → gear icon → **Web app** →
   Description `Audio Diary`, Execute as **Me**, Who has access **Only myself** → **Deploy**.
   Copy the **Web app URL** (ends in `/exec`).
7. Save both into `diary.json` in the project folder:
   ```json
   {"url": "https://script.google.com/macros/s/…/exec", "token": "…"}
   ```
8. Open the Web app URL on your phone and PC (add it to the home screen on the phone).

Then: `python tools/diary_api.py seed` puts the CDs you've listened to into the Dumper.

## Updating the page later

Paste the new `Code.gs` / `Index.html`, save, then **Deploy → Manage deployments → ✏ edit → Version: New
version → Deploy**. The URL stays the same.
