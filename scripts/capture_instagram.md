# Capturing Instagram leads

Instagram cannot be scraped with `requests`. A plain fetch of a post returns a
~624 KB JavaScript shell: no caption, no `og:description`, and — crucially — no
image `alt` text. The vacancy list lives in the post's **image**, and the only
readable transcription of it is Meta's own accessibility `alt` attribute, which
is written into the DOM client-side.

So this step needs a real browser. It takes about a minute.

## Steps

1. Open the recruiter's profile, e.g. `https://www.instagram.com/capt.norbert/`.
   You do not need to log in; the grid renders behind the sign-up prompt.
2. Open the browser console and run:

```js
async function harvest(){
  const seen = new Map();
  for (let i = 0; i < 6; i++) {
    document.querySelectorAll('a[href*="/p/"], a[href*="/reel/"]').forEach(a => {
      const img = a.querySelector('img'); if (!img) return;
      const alt = img.alt || ''; if (alt.length < 40) return;
      seen.set(a.getAttribute('href'), alt);
    });
    window.scrollBy(0, window.innerHeight * 2);
    await new Promise(r => setTimeout(r, 1400));
  }
  return [...seen.entries()].map(([h, alt]) => ({
    account: location.pathname.replace(/\//g, ''),
    url: 'https://www.instagram.com' + h,
    alt,
    captured_on: new Date().toISOString().slice(0, 10)
  }));
}
copy(JSON.stringify({captured_on: new Date().toISOString().slice(0,10),
  method: "browser alt-text capture (Meta auto-OCR of the post image)",
  posts: await harvest()}, null, 1));
```

3. Paste the clipboard into `data/informal/instagram_<YYYY-MM-DD>.json`.
4. Run `scripts/scrape_all.py` (or `sources/instagram.py` alone). Snapshots
   accumulate — old ones are still read, so history builds up.

## What the alt text looks like

```
Photo by Norbert Rebello on September 04, 2026. May be a graphic of text that
says "VIKING WE'RE HIRING! -VIDEO TECHNICIAN -HOTEL PURSER -1ST HOUSEKEEPER
-ASST CHIEF HOUSEKEEPER -STATEROOM STEWARD"
```

`sources/instagram.py` strips the `"Photo by … May be … that says"` wrapper and
keeps the transcription.

## Accounts

Listed in `scripts/employers.json → instagram_accounts`. Add recruiters who
actually post cruise hotel vacancies. Everything captured is filtered by the
housekeeping gate first, then scored by `trust.py`, so an account that posts a
mix of unrelated jobs is harmless — it just yields fewer leads.

## A caution about what this is

These are **leads, not vacancies**. The point is to learn that a line is hiring,
then apply through that line's own careers site. Anything scored `high_risk` by
`trust.py` — above all, anything asking the candidate for money — is dropped
before it reaches the dashboard.
