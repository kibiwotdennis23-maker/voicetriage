# VoiceTriage

A phone-call (IVR) health triage platform that works in any language, on any phone. The caller picks a language, answers 5 to 8 yes/no danger-sign questions with the keypad, hears what to do (go now, go today, go within 3 days, or manage at home) and the facility to go to, and the clinic gets an alert on a dashboard.

**Key idea:** the medical logic and the languages are separate. The decision tree is written once (`data/triage_tree.json`). Each language is a folder of prompts and audio (`languages/<code>/`). Adding a language needs translation and recordings, not code.

## Status (read this first)

- **Clinical content is a DRAFT.** The questions follow IMCI-style danger signs but have not been validated by a clinician. Do not use with real patients until nurses have reviewed the tree against Kenya MoH / IMCI guidance.
- **English and Kiswahili prompts are drafts** (`reviewed: false`). A native speaker must review them.
- **Kalenjin is scaffolded but empty.** Kalenjin has no text-to-speech voice, so it needs native-speaker recordings. Until a pack is complete it is never offered to callers.
- **Not yet tested against Africa's Talking.** The voice XML (`GetDigits`, `Say`, `Play`, `Redirect`) and SMS call follow their documented formats, and everything else is covered by automated tests, but run it on their sandbox before trusting it.
- Facilities in `data/facilities.json` are **sample data**.

## Try it in 2 minutes

```bash
pip install -r requirements.txt
python -m pytest                      # 37 tests
python -m voicetriage simulate --lang sw   # walk the triage in your terminal
python -m voicetriage serve --dev     # server on http://127.0.0.1:5000
```

Dashboard: open `http://127.0.0.1:5000/dashboard/` and use the token `dev-token`.

Fake a call (second request presses 1 for English):

```bash
curl -s -d "sessionId=t1&isActive=1&callerNumber=+254711000111" localhost:5000/voice
curl -s -d "sessionId=t1&isActive=1&callerNumber=+254711000111&dtmfDigits=1" localhost:5000/voice
```

## The call

1. Language menu (every ready language, each spoken in its own language)
2. Consent: press 1 to let the clinic see your answers and number, 2 to get advice without sharing
3. Who is sick: child under 5, pregnant woman, or anyone else
4. Up to 7 yes/no danger-sign questions (1 = yes, 2 = no)
5. Advice: **emergency**, **today**, **within 3 days** or **home care**
6. For the first three: choose county, hear the facility, and (with consent) an alert goes to the dashboard. Emergency and "today" cases also send an SMS to the facility. The SMS never contains the caller's number.

Wrong key or silence three times ends the call politely. If anything fails, the caller is told to go to the nearest facility.

## Add a language (for example Kalenjin)

```bash
python -m voicetriage scaffold kln "Kalenjin"        # already done for Kalenjin
python -m voicetriage sheet kln > kalenjin_sheet.csv # translators / voice talent fill this in
```

The sheet lists every prompt with the English reference and the audio file name to deliver (`<key>.mp3`). Then:

1. Put the recordings in `languages/kln/audio/`.
2. In `languages/kln/pack.json`, add the file names under `"audio"` (and text under `"prompts"` if you have it).
3. `python -m voicetriage validate` shows what is still missing. Once nothing is missing the language appears on the menu automatically.

Prompts such as `menu` and `region_*` end with the word "press"; the number clip (`digit_1` to `digit_9`) is played straight after, so one recording works wherever the language lands on the menu.

For production set `VT_REQUIRE_REVIEWED=1`, so only packs marked `"reviewed": true` are offered.

## Africa's Talking setup

1. Create an app in their sandbox and set the **voice callback URL** to `https://<your-host>/voice` (add `?s=<secret>` if you set `VT_WEBHOOK_SECRET`).
2. Set `VT_BASE_URL` to that public https address so audio files can be fetched.
3. For SMS: `VT_SMS_MODE=sandbox`, `AT_USERNAME`, `AT_API_KEY`.

## Configuration

| Variable | Purpose |
|---|---|
| `VT_TOKENS` | Dashboard tokens, `token=FACILITY_ID` or `token=*` for all facilities, comma separated |
| `VT_SECRET` | Key for hashing caller numbers (set it, or refs change on restart) |
| `VT_WEBHOOK_SECRET` | Shared secret required on the voice callback |
| `VT_BASE_URL` | Public URL, used for audio and callbacks |
| `VT_SMS_MODE` | `dry_run` (default), `sandbox` or `live` |
| `VT_ALERTS_PER_HOUR` | Alerts one phone number may create per hour (default 3) |
| `VT_DB` | SQLite file path |
| `VT_REQUIRE_REVIEWED` | `1` = offer only reviewed language packs |

## Security and privacy so far

- Consent first; callers who decline still get advice and nothing is stored beyond the call.
- Call sessions (which hold the number) are deleted when the call ends.
- Alerts hold group, reported signs and urgency only. The dashboard shows a masked number; revealing it is logged in an audit table.
- Facility tokens only see their own facility's alerts (other facilities return 404).
- Per-number rate limit, request size limit, strict CSP on the dashboard, constant-time token checks.
- Keypad only: no voice recordings are taken.

**Still to do before any pilot:** encryption at rest (SQLCipher or Postgres with disk encryption), per-user staff accounts instead of shared tokens, HTTPS and a real reverse proxy, a retention policy, a data protection impact assessment under the Kenya Data Protection Act, and a pen test of the webhook and dashboard (a good chapter for the ethical hacking write-up).

## Layout

```
data/triage_tree.json    the decision tree (language-free)
data/facilities.json     regions and facilities (sample data)
languages/<code>/        pack.json + audio/
voicetriage/engine.py    tree walking and validation
voicetriage/callflow.py  the phone call state machine
voicetriage/app.py       Flask: /voice, dashboard API, audio
voicetriage/cli.py       validate, scaffold, sheet, simulate, serve
dashboard/               plain HTML/JS clinic dashboard
tests/                   pytest suite
```

## Next steps

1. Nurse review of the tree; adjust questions and urgency levels.
2. Native-speaker translation and recording for Kalenjin, then other languages.
3. Run on the Africa's Talking sandbox with a real phone.
4. Nearest-facility by sub-county, real facility data, plug the dashboard into the Hospital Management System.
5. Phase 2: speech input for low-resource languages from consented recordings.
