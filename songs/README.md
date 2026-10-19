# songs/ - the offline songbook

Any song in this folder is found **before** the app asks a model, and is played
back exactly as written. No API key, no network, no guessing. Drop a file in
here, restart nothing, and type the song name in the app.

Supported files:

| File | What it is |
| --- | --- |
| `*.abc` | ABC notation - the format of the free tune archives (thesession.org, abcnotation.com, the Nottingham dataset) |
| `*.txt` | a compact melody line, e.g. `C4 D4 E4:2 \| F4 G4` with an optional `# Title` first line |
| `*.json` | this app's own lesson shape: `{"title": ..., "tempo": 100, "steps": [{"notes": ["C4"], "beats": 1}]}` |

Title matching is fuzzy, like the built-in songs: `washerwoman` finds
"The Irish Washerwoman".

## Getting ABC files

Traditional (Irish and Scottish) tunes come straight from thesession.org:

    python tutor.py --fetch "The Irish Washerwoman"
    python tutor.py --songbook

That writes `songs/the-irish-washerwoman.abc` (its tune text plus a `T:` title and
`K:` key header) and shows the parsed step count. thesession.org is free and needs
no key - it is also polite to keep a slow hand on it, since it is a community
site. It only holds traditional tunes, so anything modern will come back as "no
such tune"; those still go to the model.

The site's search is loose, so the name is checked before anything is saved: ask
for "Blinding Lights" and it says it has no such tune (rather than quietly saving
the nearest jig, which would then shadow the model with a wrong song). Tune types
are ignored, so "Morrison's Jig" matches the tune filed as "Morrison's".

Larger collections to copy files from by hand:

- **abcnotation.com** - a search engine over ~100k ABC tunes (classical, folk,
  everything). Use "download the ABC" and save it here.
- **Nottingham dataset** - ~1000 British and Irish folk tunes, ABC and MIDI,
  public domain.
- **Mutopia / OpenScore** - public-domain classical scores (MusicXML, not ABC).

## Why bother

For anything in this folder the app is *better* than the model: the notes are
exact, they arrive instantly, they work offline, and they never change between
lookups. The model stays as the fallback for songs nobody has written down here.
