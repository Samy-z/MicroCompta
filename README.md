# MicroCompta

A light personal accounting desktop app for a French micro-entrepreneur: the payments
ledger, invoices, limits, deadlines, and a backup of every document to your own Google
Drive. It works fully offline and catches up when it can.

> **It reminds and adds up. It doesn't give tax advice**, it doesn't do e-reporting, and it
> doesn't file anything with URSSAF. Open questions are listed in the app (Annual tab) and
> [below](#still-open).

## Start

```bash
run.bat
```

The first run builds `.venv`, installs what it needs, and makes shortcuts on the Desktop and
in the Start Menu. Python 3.11 or later must be installed. At first launch, **Settings** opens
on its own (later, it's the gear icon at the top right, next to Help). Enter your identity and
start date, then add your client.

To only build the environment, without opening the app:

```bash
run.bat --setup
```

If setup stops on a "long path" error, the folder is nested too deeply for one of PySide6's
files. Move it somewhere shorter, or enable Windows long paths, and run it again. A failed
setup is retried on the next run rather than opening a half-installed app.

Reminders fire only while the app runs, so closing the window keeps it in the tray. Quit from
the tray icon's menu. To have it start with Windows, once:

```bash
.venv\Scripts\python.exe scripts\make_shortcut.py --startup
```

## Google Drive backup: connecting it

You do this once, in your own browser, in about 10 minutes. The app never sees your Google
password. It asks only for the `drive.file` scope, so it can see only the files it created.

1. Go to <https://console.cloud.google.com/> and create a project, for example `MicroCompta`.
2. **APIs & Services > Library**: enable **Google Drive API**.
3. **Google Auth Platform**: set the app name and your email. Audience: **External**.
4. **Publish the app, so its status is "In production".** This step matters. While the app is
   in "Testing", Google cancels the sign-in every 7 days and the backup stops until you sign in
   again. `drive.file` isn't a sensitive scope. If Google shows a warning screen when you sign
   in, it's about your own app.
5. **Clients > Create client**, type **Desktop app**. Download the JSON.
6. In MicroCompta, **Backup** tab: **Choose client file...**, pick that JSON, then **Sign in with
   Google**. Tick the Drive box on the consent screen.

The app keeps a copy of the client file and the token here, outside the project folder:

```
%LOCALAPPDATA%\MicroCompta\secrets\
```

Anyone with access to your Windows account can read that folder, as with any file you own. The
JSON you downloaded can be deleted afterwards. **Sign out** forgets the token on this computer
and changes nothing in Drive. To revoke the app's access for good, use your Google account's
security page.

### What is uploaded, and where

| Kind | When | In Drive |
| --- | --- | --- |
| Invoice and credit note PDFs | when issued | `MicroCompta/<year>/factures/` |
| Attached receipts | when attached | `MicroCompta/<year>/recus/` |
| CSV and PDF exports | when exported | `MicroCompta/<year>/exports/` |
| Database snapshot (zipped), ledger CSV, invoice register CSV | a few minutes after a change, hourly if changed, and on quit | `MicroCompta/<year>/sauvegardes/` |

A document counts as **uploaded** only when Drive reports the same checksum as the local file.
The queue is stored in the database, so it survives a restart:

- **pending**: waiting, or waiting for a connection or sign-in. Being offline never counts
  as a failure. Retries back off from 1 minute to 1 hour.
- **uploaded**: verified.
- **failed**: needs a look, with the reason shown. Retried every 6 hours, or press **Retry**.

Nothing is ever deleted from Drive. If a checksum doesn't match, the wrong copy stays there and
the upload runs again.

### Restoring without the app

The CSVs open in any spreadsheet (semicolons, decimal commas, UTF-8). A snapshot is a zipped
DuckDB database:

```bash
python -c "import duckdb; print(duckdb.connect('microcompta.duckdb', read_only=True).sql('SELECT * FROM ledger'))"
```

To restore on a new computer: install the app, unzip the snapshot to
`%LOCALAPPDATA%\MicroCompta\microcompta.duckdb` before the first launch, and copy the PDFs back
into `%LOCALAPPDATA%\MicroCompta\documents\` so the integrity check can find them.

## How the records work

**Payments ledger (livre des recettes).** One entry per payment received, counted on the date
received. Each stores its gross, rate, fee and net separately. Entries can't be edited: a
correction is a reversing entry with a reason. Totals every 3 months, exports in CSV and PDF.

**Invoices.** A monthly summary drafted from that month's payments. Drafts are fine without a
SIREN, but a final invoice needs a valid one. Numbers are unbroken across all documents and
years (`FA-2027-0012`, `AV-2027-0013`), chronological, and taken only when issuing succeeds in
full. An issued invoice can't change. A correction is a credit note.

**USD invoices** follow [economie.gouv.fr](https://www.economie.gouv.fr/entreprises/gerer-son-entreprise-au-quotidien/gerer-sa-comptabilite-et-ses-demarches/comment-facturer-dans-une-monnaie-etrangere):
the amount in USD, its euro counter-value, and the rate applied, using the ECB's rate of the
day. You enter the rate from the ECB's site, because the app has no network access beyond Drive.
The ECB publishes nothing at weekends, so use the last rate and its date.

**The rate on an invoice and the rate in the ledger are separate.** An invoice's euro value uses
the ECB rate on its issue date. Turnover uses the ledger: each payment's own rate on the date
received. The Invoices tab shows both numbers when they differ.

**Immutability.** DuckDB has no triggers, so the database can't refuse a change by itself. The
app's only write route refuses to touch the ledger and the invoice register. Both are also hash
chains, and issued PDFs are checksummed, so a change made any other way (a direct SQL session, a
restored file) raises a red banner at the next check. The check runs at launch and every 6 hours.

**Info bubbles.** Hold the mouse over any number, button or line to see what it means. The same
words are given to screen readers, and Tab onto a number card to show its bubble from the
keyboard. A test fails if a button, field, number or column has no bubble.

**Figures.** Every limit, rate and fixed date is in effective-dated, editable data under
**Settings > Figures**, with its source. To change one over time, add a row with a later date.
Seed values are in `microcompta/data/figures_seed.json` and never overwrite an edit. Sources were
last checked on 2026-11-04, and a yearly reminder asks you to re-check them.

## Language

The app starts in French. English is an option under Settings > Language, and applies straight
away. Invoices, credit notes and the livre des recettes stay in French either way, because they
are French legal records. Stored values are language-neutral, so switching can't change a record.

English is the source language: the text in the code is the key. To add a language, copy
`microcompta/data/i18n/fr.json` to `<code>.json`, change `language_name`, and translate the
values. It then appears in Settings with no code change. Tests check that the French catalogue
covers every string in the code, with matching `{placeholders}`, and that the French screens
show no English. Number and date formats are in `microcompta/i18n.py`.

## Still open

These aren't settled by the official sources read so far. The app labels them where they matter.

| Question | Who answers | What the app does |
| --- | --- | --- |
| Which USD rate for turnover | URSSAF | Rate on each entry, ECB by default. A setting. |
| Turnover before or after provider fees | URSSAF | Gross by default, a setting. [F23257](https://entreprendre.service-public.gouv.fr/vosdroits/F23257) says no commission or fee is deducted, but doesn't name Stripe or PayPal. |
| Does a non-EU business client count towards the VAT franchise? | SIE | Per-client flag, excluded by default. Probably right; an inference from BOFiP s.180. |
| Any invoice mention beyond art. 293 B for a non-EU client | SIE | Editable setting. |
| Versement libératoire with no French reference income | SIE | Reminder only. |
| Does ACRE reduce the versement libératoire part? | URSSAF | Assumes not. |
| Formation professionnelle on top of the flat rate? | URSSAF | Assumes nothing extra, per F36232. |
| Does a prorated first year count as a year over the ceiling? | URSSAF or SIE | Counts it, and says it's unstated. |

## Data location

| What | Where |
| --- | --- |
| Database | `%LOCALAPPDATA%\MicroCompta\microcompta.duckdb` |
| Documents | `%LOCALAPPDATA%\MicroCompta\documents\<year>\<kind>\` |
| OAuth client and token | `%LOCALAPPDATA%\MicroCompta\secrets\` |
| Log | `%LOCALAPPDATA%\MicroCompta\logs\` |

Set `MICROCOMPTA_DATA_DIR` to use another folder. Tests and the smoke script always use a
temporary one, with fake data. The app's only network access is Google's API hosts, enforced in
one place in `microcompta/backup/drive_client.py`, along with a refusal of any verb that could
delete.

## Development

```bash
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

```bash
.venv\Scripts\python.exe -m pytest tests
```

```bash
.venv\Scripts\python.exe scripts\ui_smoke.py
```

`ui_smoke.py` builds the real window offscreen on fake data and saves `screenshots/`.
`build_assets.py` regenerates the logo and icon.

Layout: `microcompta/core` holds the records and rules, with no Qt in it. `backup` holds the
queue, REST client and sign-in. `ui` holds the panels, theme, tray and workers. Structure and
look follow PolyClusters.

On Windows, a GUI app started from a shell inside a sandboxed agent may get its data directory
redirected. Start it through `explorer.exe` if that applies.
