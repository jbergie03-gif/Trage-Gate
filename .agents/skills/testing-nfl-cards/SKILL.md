---
name: testing-nfl-notes-publishing
description: Runtime checks for NFL notes routes, weekly-page navigation, subscription cleanup, and caption CLI guards.
---

# NFL notes publishing tests

Work from `nfl_model/`; notes_build.py and cardapi/server.py use stdlib Python.
Do not fit a model just to test notes. The production droplet may not have enough
RAM for model fitting.

## Browser and local route coverage

- Record the public notes -> weekly numbers -> notes -> pick-sheet links.
  Compare all generated game sections and FACT/UNKNOWN/READ labels to the notes
  source, and visually inspect label styles. Test both `/notes` and `/notes.html`.
- For the missing-file fallback, start an isolated card API on an unused port.
  Set `CARD_DATA_DIR` to a fresh temporary directory and explicitly set
  `PICKSHEET`, `WEEKPAGE`, `KICKOFFS`, and `NOTESPAGE`. Set NOTESPAGE to a
  nonexistent temporary path: never remove a deployed file to cause a 404.
- Both notes aliases should return 404 **text/html**, with a functioning `/week`
  link. Unknown unrelated paths can legitimately return 404 JSON.
- If kickoff regression testing is requested, check real current slate/times
  first. A future-only slate cannot prove a real elapsed live kickoff. Clearly
  distinguish an injected browser clock from an isolated altered manifest and
  from a real wall-clock test; do not submit a production test card merely to
  manufacture evidence.

## Subscription lifecycle

Only test live signup when explicitly authorized. Use a distinctive test email.
Record `/health` card/subscriber counts before signup, after signup, and after
unsubscription. Use the normal weekly-page form and genuine signed unsubscribe
URL; confirm subscribers return to baseline (normally zero). Do not delete logs.

When no mailbox delivery is part of the test, an authorized operator can derive
the exact test email's token with the deployed server's `token(email)` function.
Confirm the running service's CARD_DATA_DIR first. Import with
PYTHONDONTWRITEBYTECODE=1; do not expose the signing secret. Report this as
emailed-style link validation, not actual email delivery.

## Caption CLI

Run `python3 notes_build.py notes/<season>-w<week>.md --caption`.
Compare generated text with lead paragraphs, captioned games in source order,
and tail paragraphs. Confirm tracked source/artifacts are unchanged afterward.

Use copies in a **fresh directory** for malformed cases: prior rejected runs may
have left outputs from older implementations and can invalidate no-write checks.
Test lowercase/uppercase/mixed-case URLs, implemented bare-domain patterns,
2200/2201-character boundaries, and repeatable lead/tail ordering.
Rejection should exit nonzero, print a clean error, and write neither HTML nor
TXT. Also seed existing outputs and verify rejection preserves their bytes.
Inspect what split/repeated fields actually emit; only lead/tail are repeatable.
Distinguish a guard's implemented patterns from a blanket all-destinations policy
(bare IPs and other TLDs may not be recognized).

## Devin Secrets Needed

- Public routes and isolated local checks require none.
- Authorized live token derivation requires the provisioned `do_nfl_scanner`
  SSH key (normally `~/.ssh/do_nfl_scanner`) and read access to the service data.
  Never print the private key or subscriber signing secret.
