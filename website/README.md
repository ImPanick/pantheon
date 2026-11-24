# getpantheon.ai

The public site for Pantheon: a landing page, the Apollo launch article and the install guide.
It is plain HTML, CSS and JavaScript with no build step, served by Cloudflare as a Worker with
static assets. Nothing here talks to a server, sets a cookie or tracks anyone.

```
website/
  wrangler.jsonc        Cloudflare config (assets-only Worker named "getpantheon")
  public/               everything that gets served
    index.html          the landing page
    apollo/             the Apollo launch article
    404.html            the not-found page
    _headers            security headers and caching
    assets/
      site.css, site.js page styles and behaviour
      hero.js           the three.js dome in the hero
      vendor/           three.js r170 (MIT)
      fonts/            Geist, Geist Mono, Instrument Serif (OFL)
      img/              product screenshots, dark and light
  (licence texts live in the repo's top-level licenses/ folder)
```

## Preview locally

Any static server works. From the repo root in PowerShell:

```powershell
cd website\public
python -m http.server 8080
```

Then open http://localhost:8080. To run it exactly as Cloudflare will (headers, 404 handling),
use Wrangler instead, which needs Node:

```powershell
cd website
npx wrangler dev
```

## Put it on getpantheon.ai

This is a one-time setup in the Cloudflare dashboard. After it, every push to the chosen branch
redeploys the site.

1. Open **Workers & Pages** and choose **Create application**.
2. Pick **GitHub**, sign in if asked, and choose the `ImPanick/pantheon` repository.
3. Set the Worker name to `getpantheon`. It has to match `name` in `wrangler.jsonc` or the build fails.
4. In the build settings, set **Root directory** to `website`. Leave **Build command** empty.
   **Deploy command** stays `npx wrangler deploy`.
5. Choose **Save and Deploy**. The site comes up on a `*.workers.dev` address first.
6. In the Worker, go to **Settings**, then **Domains & Routes**, choose **Add**, then **Custom Domain**,
   and enter `getpantheon.ai`. Do the same for `www.getpantheon.ai` if you want it.
   If an old DNS record already points `getpantheon.ai` somewhere, delete it first or the add fails.
7. To change which branch deploys, open **Settings**, then **Build**, and set **Git branch**.

Workers rather than Pages because Cloudflare now points new static sites at Workers. Pages still works
and the same `public` folder would deploy there unchanged.

## Rules for the copy

- Every claim about Pantheon has to be true of the code on the branch the site deploys from.
- No em dashes. Write it the way you would say it.
- No inline scripts or styles: `_headers` sets a strict Content Security Policy, and anything inline is blocked.
- Keep it from reading as machine-made: no small-caps eyebrows over headings, no "not X, it's Y" lines,
  no lists of three for rhythm, no stat strips, no gradient glows or glass panels. Say what the thing does.
- The dome in the hero is the only animation. Everything else sits still.

## Third-party files

| File | Project | Licence |
| --- | --- | --- |
| `public/assets/vendor/three.module.min.js` | three.js 0.170.0 | MIT, `licenses/three.js-MIT-LICENSE.txt` |
| `public/assets/fonts/Geist-*.woff2`, `GeistMono-*.woff2` | Geist by Vercel | SIL OFL 1.1, `licenses/Geist-OFL.txt` |
| `public/assets/fonts/InstrumentSerif-*.woff2` | Instrument Serif | SIL OFL 1.1, `licenses/InstrumentSerif-OFL.txt` |
