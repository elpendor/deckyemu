"""The pages the transfer server serves: markup, style and the browser script.

Split from fileserver.py, which is a socket server with an HTTP dialect on top
and had four hundred lines of somebody else's front end in the middle of it. The
seam is state: everything here is a pure function of the facts it is handed, and
the server keeps the state, the lock and the sockets. So a wording change is
reading one file rather than scrolling past `do_PUT`, and the page can be
rendered from a test without a server.

**Each page is still one self-contained file, and that has to stay true.** No
external stylesheet, font or script: this is served over plain HTTP from a Deck
on somebody's home network, and every asset would be one more thing that has to
resolve from a device that may only have a route to this one host. That is why
the style, the script and even the favicon are constants substituted into the
markup rather than files beside it -- the split is in the Python, never in what
goes over the wire.

The pages are read on the sender's phone or laptop, not on the Deck, so they
follow that device: `color-scheme: dark light` with a light override, and one
centred column so a desktop browser does not stretch a line of text across a
27-inch monitor.
"""

import base64
import html


# An upload arrow over a tray, drawn rather than borrowed so it needs no asset.
#
# Declared inline for the same reason as everything else on these pages: the
# sending device may have a route to this host and nothing else. It also stops
# every page load asking for /favicon.ico, which this server answers with a 404
# and a line in the plugin log.
#
# Base64 rather than a raw `data:image/svg+xml,...` URI: the SVG contains `#`,
# quotes and angle brackets, all of which need encoding in a URI, and `%23` in
# particular would then have to survive a %-formatted template. Encoding once at
# import keeps the drawing readable here and the URI inert everywhere else.
_FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<rect width="64" height="64" rx="14" fill="#4c6ef5"/>'
    '<path d="M32 15 L45 30 H37 V42 H27 V30 H19 Z" fill="#ffffff"/>'
    '<rect x="18" y="46" width="28" height="5" rx="2.5" fill="#ffffff"/>'
    "</svg>"
)
_FAVICON = "data:image/svg+xml;base64," + base64.b64encode(
    _FAVICON_SVG.encode("utf-8")
).decode("ascii")


def human_size(count):
    if count >= 1024 ** 3:
        return "%.1f GB" % (count / 1024 ** 3)
    if count >= 1024 ** 2:
        return "%d MB" % round(count / 1024 ** 2)
    return "%d KB" % max(1, round(count / 1024))


# One stylesheet for both pages.
#
# Kept in a constant and substituted in rather than written inline, because these
# pages are built with the % operator and a literal percent in CSS then has to be
# written `%%`. That escaping has bitten this file before and there is no reason
# to keep paying attention to it: a value substituted in is never parsed as a
# format string.
#
# Colours come from custom properties with a light-scheme override, because this
# page is read on someone else's phone or laptop rather than on the Deck -- the
# plugin's own dark styling is not theirs to impose. Everything is sized in a
# single centred column so a desktop browser does not stretch one line of text
# across a 27-inch monitor.
_STYLE = """
  :root {
    color-scheme: dark light;
    --bg: #14171c; --card: #1e222a; --raised: #2a303a;
    --text: #e8eaed; --muted: #9aa1ac; --line: #333a45;
    --accent: #4c6ef5; --accent-soft: rgba(76,110,245,0.16);
    --ok: #5bd15b; --bad: #e35d5d;
    --warn: #e8a33d; --warn-soft: rgba(232,163,61,0.14);
  }
  @media (prefers-color-scheme: light) {
    :root {
      --bg: #f1f3f5; --card: #ffffff; --raised: #eceef1;
      --text: #1a1d23; --muted: #5f6672; --line: #dde0e5;
      --accent-soft: rgba(76,110,245,0.10);
      --ok: #2f9e44; --bad: #c92a2a;
      --warn: #b26a00; --warn-soft: rgba(178,106,0,0.10);
    }
  }
  * { box-sizing: border-box; }
  html { -webkit-text-size-adjust: 100%; }
  body {
    margin: 0;
    padding: 22px 16px calc(28px + env(safe-area-inset-bottom, 0px));
    font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    background: var(--bg); color: var(--text); line-height: 1.45;
  }
  main { width: 100%; max-width: 620px; margin: 0 auto; }
  h1 { font-size: 22px; margin: 0 0 4px; letter-spacing: -0.01em; }
  /* The heading and whatever second action the page has, on one line. `gap`
     rather than a margin so the row collapses to just the heading when there is
     no button, and `wrap` so a narrow phone drops the button below rather than
     squeezing the title into two words. */
  .head { display: flex; align-items: baseline; justify-content: space-between;
          gap: 10px 14px; flex-wrap: wrap; }
  /* Looks like a button, is a link: it navigates, and making it a <button> that
     sets location is more moving parts for the same result -- and one that
     stops working with scripting off. */
  a.report { flex: none; font-size: 13px; font-weight: 600; text-decoration: none;
             padding: 7px 12px; border-radius: 8px; white-space: nowrap;
             color: var(--text); background: var(--card);
             border: 1px solid var(--line); }
  a.report:hover { border-color: var(--accent); background: var(--accent-soft); }
  h2 { font-size: 12px; text-transform: uppercase; letter-spacing: .08em;
       color: var(--muted); margin: 24px 0 8px; font-weight: 600; }
  p.dir { color: var(--muted); font-size: 13px; margin: 0 0 18px;
          word-break: break-all; }
  p.keep { font-size: 13px; margin: 0 0 18px; padding: 11px 13px;
           background: var(--accent-soft); border: 1px solid var(--line);
           border-radius: 10px; }
  label.pick { display: block; padding: 26px 18px; text-align: center;
               border: 2px dashed var(--line); border-radius: 12px;
               background: var(--card); cursor: pointer;
               transition: border-color .15s ease, background .15s ease; }
  label.pick:hover, label.pick.drag { border-color: var(--accent);
                                      background: var(--accent-soft); }
  label.pick b { display: block; font-size: 16px; font-weight: 600; }
  label.pick span { display: block; margin-top: 3px; font-size: 13px;
                    color: var(--muted); }
  input[type=file] { display: none; }
  /* `minmax(0, 1fr)` rather than the implicit `1fr`, and `min-width: 0` on the
     row: a grid item defaults to `min-width: auto`, which means it refuses to
     shrink below the width of its own content. The name inside already clips
     with an ellipsis, but that never got the chance -- the track grew to fit
     the whole filename instead, and a ROM called
     UP4415-NPUB31749_00-GOATSIMULATORPS3_bg_1_fbd920a6....pkg pushed the card
     clean off the side of the page. Same mistake as the panel's own ROM button,
     in a different layout system. */
  ul { list-style: none; padding: 0; margin: 0; display: grid;
       grid-template-columns: minmax(0, 1fr); gap: 8px; }
  li { min-width: 0; background: var(--card); border: 1px solid var(--line);
       border-radius: 10px; padding: 10px 12px; font-size: 14px; }
  .row { display: flex; align-items: baseline; gap: 10px; }
  .name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis;
          white-space: nowrap; }
  .size { color: var(--muted); font-size: 12px; white-space: nowrap; }
  .bar { height: 5px; margin-top: 8px; border-radius: 3px;
         background: var(--raised); overflow: hidden; }
  .bar i { display: block; height: 100%; width: 0;
           background: var(--accent); transition: width .2s linear; }
  li.done .name::before { content: "\\2713  "; color: var(--ok); }
  li.failed .name::before { content: "\\2717  "; color: var(--bad); }
  li.failed .size { color: var(--bad); }
  /* Between two attempts: not done, not failed, and it used to look like
     neither. "reconnecting" landed in the same muted grey as the file size it
     replaced -- the one corner of the row nobody reads for news -- so the state
     that most needs noticing was the least visible thing on the page. It gets
     the third colour, its own mark, and a dimmed bar: the file has not lost
     what it had, it is simply not moving this second. */
  li.waiting { border-color: var(--warn); background: var(--warn-soft); }
  li.waiting .name::before { content: "\\21BB  "; color: var(--warn); }
  li.waiting .size { color: var(--warn); font-weight: 600; }
  li.waiting .bar i { opacity: .55; }
  form { display: flex; flex-direction: column; gap: 12px; }
  input[type=text] { font-size: 30px; width: 100%; padding: 12px;
                     text-align: center; letter-spacing: .28em;
                     border-radius: 10px; border: 1px solid var(--line);
                     background: var(--card); color: inherit; }
  button { font-size: 16px; padding: 13px 20px; border-radius: 10px; border: 0;
           background: var(--accent); color: #fff; font-weight: 600;
           cursor: pointer; }
  .bad { color: var(--bad); }
"""

# The upload page's behaviour, kept out of the format string for the same reason
# as the stylesheet: it builds a percentage, and `'%'` inside a %-formatted
# template would have to be written `'%%'`.
_SCRIPT = """
const queue = document.getElementById('queue');
const zone = document.getElementById('zone');
const already = document.getElementById('already');
const arrivingHeading = document.getElementById('arrivingHeading');
const receivedHeading = document.getElementById('receivedHeading');

// A file moves between the two lists exactly as it does on the Deck: it is
// Arriving while it is in flight, and Received once the server has it. Leaving
// finished uploads in the first list would make "Arriving" a lie within
// seconds, and is what the panel does not do.
//
// A failed one stays put. It did not arrive, and moving it under Received --
// or hiding it -- would be the page claiming something the Deck does not have.
function reflowHeadings() {
  arrivingHeading.style.display = queue.children.length ? '' : 'none';
  if (already.children.length) receivedHeading.style.display = '';
}

function humanSize(n) {
  if (n >= 1073741824) return (n / 1073741824).toFixed(1) + ' GB';
  if (n >= 1048576) return Math.round(n / 1048576) + ' MB';
  return Math.max(1, Math.round(n / 1024)) + ' KB';
}

// How many uploads are still running, so leaving the page can be questioned.
//
// Closing the tab aborts the request, and a multi-gigabyte ROM then has to start
// over from nothing -- there is no resume. The Deck cleans up the half-written
// file either way, so this guards the user's time rather than the disk.
//
// Advisory only: the browser decides the wording, the user can still leave, and
// several mobile browsers ignore beforeunload entirely. The server therefore
// still treats a vanished connection as normal, because it is.
let active = 0;

window.addEventListener('beforeunload', (event) => {
  if (active === 0) return;
  event.preventDefault();
  // Required for the prompt to appear at all; the string itself is ignored by
  // every current browser in favour of its own wording.
  event.returnValue = '';
  return '';
});

// Keeping the screen on while files are moving.
//
// A phone that locks its screen suspends the upload, which is the commonest way
// a transfer dies: a multi-gigabyte ROM is ten or twenty minutes of holding a
// device that would rather go to sleep. The lock is only granted to a visible
// page and is dropped when the page is hidden, so it is asked for again every
// time the page comes back. Browsers without it lose nothing else.
let wakeLock = null;

function keepAwake() {
  if (wakeLock || !navigator.wakeLock || !active) return;
  navigator.wakeLock.request('screen').then((lock) => {
    wakeLock = lock;
    lock.addEventListener('release', () => { wakeLock = null; });
  }).catch(() => undefined);
}

function letSleep() {
  const lock = wakeLock;
  wakeLock = null;
  if (lock) { try { lock.release(); } catch (e) { /* already gone */ } }
}

document.getElementById('pick').addEventListener('change', (event) => {
  const files = [...event.target.files];
  event.target.value = '';
  files.forEach(enqueue);
});

// Drag and drop, for the desktop half of the audience. The document-level
// handlers matter as much as the drop zone's: without them a file dropped just
// outside the target replaces the page with itself, losing the queue.
['dragenter', 'dragover', 'dragleave', 'drop'].forEach((name) => {
  document.addEventListener(name, (event) => event.preventDefault());
});
['dragenter', 'dragover'].forEach((name) => {
  zone.addEventListener(name, () => zone.classList.add('drag'));
});
['dragleave', 'drop'].forEach((name) => {
  zone.addEventListener(name, () => zone.classList.remove('drag'));
});
zone.addEventListener('drop', (event) => {
  [...(event.dataTransfer ? event.dataTransfer.files : [])].forEach(enqueue);
});

// One at a time, in the order they were chosen.
//
// Eight ROMs picked together used to start eight PUTs at once. They share one
// wifi link and one disk, so they finish no sooner than they would in turn --
// and one blink of the connection then set all eight back instead of one. In
// turn, the bar at the top of the list is also the file that is actually
// moving, which is what somebody watching it assumes anyway.
const pending = [];
let current = null;

function pump() {
  if (current) return;
  current = pending.shift() || null;
  if (!current) { letSleep(); return; }
  keepAwake();
  attempt(current);
}

// Enough to tell "the rest of this file" from "a different file with the same
// name". The Deck keys its half-file on this and will not splice two files
// together, which is the one way resuming could produce a broken game quietly.
function fingerprint(file) {
  return file.size + '-' + (file.lastModified || 0);
}

// How much of this file the Deck already has. Asked before every attempt, so
// the first upload and the fifth retry are the same code path -- and re-picking
// a file after reloading this page carries on rather than starting again.
function askPending(file) {
  return new Promise((resolve) => {
    const probe = new XMLHttpRequest();
    probe.open('GET', PENDING_BASE + encodeURIComponent(file.name)
                      + '?fp=' + encodeURIComponent(fingerprint(file)));
    probe.addEventListener('load', () => {
      let received = 0;
      try { received = JSON.parse(probe.responseText).received || 0; } catch (e) { received = 0; }
      resolve(received > file.size ? 0 : received);
    });
    // An answer we cannot get is not a reason to refuse to send: start over.
    probe.addEventListener('error', () => resolve(0));
    probe.send();
  });
}

// How many attempts in a row may move nothing before this is called failed. An
// attempt that transferred bytes resets it, so a slow connection dropping every
// few minutes keeps going, while a Deck that has gone away stops asking.
const MAX_STALLS = 6;
const MAX_TRIES = 30;

function attempt(job) {
  askPending(job.file).then((offset) => {
    if (job !== current) return;
    job.tries += 1;
    // Out of the waiting state and back to an ordinary row: this is a transfer
    // again rather than one that stopped.
    job.row.className = '';
    job.size.textContent = offset > 0
      ? 'resuming at ' + Math.round((offset / job.file.size) * 100) + '%'
      : humanSize(job.file.size);

    const request = new XMLHttpRequest();
    request.open('PUT', UPLOAD_BASE + encodeURIComponent(job.file.name));
    request.setRequestHeader('X-Upload-Id', fingerprint(job.file));
    request.setRequestHeader('X-Upload-Offset', String(offset));

    // Bytes this attempt handed to the network. Not what the Deck has -- only
    // it knows that, and the next attempt asks -- but enough to tell an attempt
    // that achieved something from one that never got started.
    let moved = 0;
    request.upload.addEventListener('progress', (e) => {
      if (!e.lengthComputable) return;
      moved = e.loaded;
      job.fill.style.width = (((offset + e.loaded) / job.file.size) * 100) + '%';
    });
    request.addEventListener('load', () => {
      if (request.status === 200) finish(job);
      else again(job, moved, request.responseText || ('failed (' + request.status + ')'));
    });
    request.addEventListener('error', () => again(job, moved, 'connection lost'));
    request.addEventListener('abort', () => again(job, moved, 'interrupted'));
    // Only the part the Deck does not have. An offset equal to the whole file
    // sends nothing and asks it to finish what it is holding, which is what a
    // connection that died on the last chunk leaves behind.
    request.send(job.file.slice(offset));
  });
}

function again(job, moved, message) {
  job.stalls = moved > 0 ? 0 : job.stalls + 1;
  if (job.stalls > MAX_STALLS || job.tries >= MAX_TRIES) { fail(job, message); return; }
  // "failed" on a row that is about to try again would be a lie, and this is
  // the state the page is in for most of a bad connection. Marked on the row
  // rather than said in the corner, so it is a different-looking thing and not
  // a different word in the same grey.
  //
  // The Deck calls this "Paused" and this side calls it "reconnecting" on
  // purpose: they are the same state seen from the two ends, and the sender is
  // the end that is doing something about it. Anything the two must call by the
  // same name is checked in test_transfer_wording.py.
  job.row.className = 'waiting';
  job.size.textContent = 'reconnecting';
  job.timer = setTimeout(() => {
    job.timer = 0;
    attempt(job);
  }, Math.min(1000 * Math.pow(2, job.stalls), 10000));
}

function finish(job) {
  job.bar.remove();
  job.size.textContent = humanSize(job.file.size);
  job.row.className = 'done';
  // Newest first, matching the order the server lists what it already had.
  already.insertBefore(job.row, already.firstChild);
  settle(job);
}

function fail(job, message) {
  job.bar.remove();
  job.row.className = 'failed';
  job.size.textContent = message;
  settle(job);
}

function settle(job) {
  active -= 1;
  if (current === job) current = null;
  reflowHeadings();
  pump();
}

// A locked phone suspends the upload *and* throttles the timer that would retry
// it, so coming back is the moment to try again rather than the end of a
// backoff that was not counting while the page was asleep.
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState !== 'visible') return;
  keepAwake();
  if (current && current.timer) {
    clearTimeout(current.timer);
    current.timer = 0;
    attempt(current);
  }
});

function enqueue(file) {
  const row = document.createElement('li');
  const head = document.createElement('div');
  head.className = 'row';
  const name = document.createElement('div');
  name.className = 'name';
  name.textContent = file.name;
  const size = document.createElement('div');
  size.className = 'size';
  size.textContent = humanSize(file.size);
  head.appendChild(name);
  head.appendChild(size);
  const bar = document.createElement('div');
  bar.className = 'bar';
  const fill = document.createElement('i');
  bar.appendChild(fill);
  row.appendChild(head);
  row.appendChild(bar);
  queue.appendChild(row);
  reflowHeadings();

  // Every attempt at this file shares one row and one count. `active` is
  // decremented exactly once, by whichever of finish and fail gets there --
  // a per-request decrement is what made this go negative and question every
  // attempt to leave the page forever after.
  active += 1;
  pending.push({ file: file, row: row, bar: bar, fill: fill, size: size,
                 stalls: 0, tries: 0, timer: 0 });
  pump();
}
"""


def code_page(locked, remaining, bad=False, digits=6):
    """The form shown at the root, asking for the six-digit code.

    A GET form, so it works with scripting disabled and needs no CSRF thinking --
    the code itself is the only credential and submitting it is idempotent.

    `locked` and `remaining` are read off the server's own counters under its
    lock and passed in, rather than looked up here: this file may not reach for
    state, or rendering a page becomes something that can only happen inside a
    running server.
    """
    if locked:
        # Names the two buttons as they are labelled on the Deck. The sender is
        # reading this on another device and cannot see the panel, so "restart
        # the transfer" left them looking for a control with that name, which
        # does not exist.
        message = (
            '<p class="bad">Too many wrong codes. On your Deck, press '
            "<b>Stop receiving</b> and then <b>Start receiving</b> for a new "
            "code.</p>"
        )
        form = ""
    else:
        message = (
            '<p class="bad">That code is not right. %d attempt(s) left.</p>' % remaining
            if bad
            else "<p>Enter the code shown on your Deck.</p>"
        )
        form = """<form method="get" action="/">
  <input type="text" name="code" inputmode="numeric" pattern="[0-9]*" maxlength="%d"
         autocomplete="one-time-code" autofocus placeholder="000000">
  <button type="submit">Continue</button>
</form>""" % digits

    # Centred in the viewport rather than at the top: this page holds one control
    # and nothing else, so there is nothing below the fold to scroll toward.
    return """<!doctype html>
<html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<link rel="icon" href="%(icon)s">
<title>Transfer to Deck</title>
<style>%(style)s
  body { min-height: 100vh; display: grid; place-items: center; }
  main { max-width: 22rem; text-align: center; }
  h1 { margin-bottom: 14px; }
</style>
</head><body><main>
<h1>Transfer to Deck</h1>
%(message)s
%(form)s
</main></body></html>""" % {
        "message": message,
        "form": form,
        "style": _STYLE,
        "icon": _FAVICON,
    }


# Offered only when the link is durable, and it is a hint rather than a button
# because no browser will let a page bookmark itself. window.external.AddFavorite
# and window.sidebar.addPanel were both removed years ago and nothing replaced
# them; the install-to-home-screen route needs a secure context, which plain HTTP
# on a LAN address is not. So the most a page can honestly do is name the gesture,
# and name the right one for the device holding it.
_BOOKMARK_HINT = """  <p class="keep" id="keep"></p>
<script>
(function () {
  const ua = navigator.userAgent;
  const line = document.getElementById('keep');
  let how;
  if (/iPhone|iPad|iPod/.test(ua)) {
    how = 'tap Share, then "Add to Home Screen"';
  } else if (/Android/.test(ua)) {
    how = 'open the browser menu, then "Add to Home screen"';
  } else if (/Mac OS X/.test(ua)) {
    how = 'press Cmd-D';
  } else {
    how = 'press Ctrl-D';
  }
  line.textContent = 'Keep this page - ' + how + ' - and next time it opens straight here, with no code to type.';
})();
</script>"""


def upload_page(directory, arrived, token, durable, report):
    """The upload page. Deliberately one self-contained file, no assets.

    `arrived` is (name, size) pairs oldest first -- the newest is shown at the
    top, which is where somebody watching a transfer is looking. `durable` adds
    the bookmark hint, `report` the button beside the heading.
    """
    listed = "".join(
        '<li class="done"><div class="row"><div class="name">%s</div>'
        '<div class="size">%s</div></div></li>'
        % (html.escape(name), human_size(size))
        for name, size in reversed(arrived)
    )

    return """<!doctype html>
<html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<link rel="icon" href="%(icon)s">
<title>Transfer to Deck</title>
<style>%(style)s</style>
</head><body>
<main>
  <div class="head">
    <h1>Transfer to Deck</h1>
%(report)s
  </div>
  <p class="dir">Saving into %(dir)s</p>
%(keep)s
  <label class="pick" id="zone">
    <b>Choose files</b>
    <span>or drag them here</span>
    <input id="pick" type="file" multiple>
  </label>

  <!-- The same two words the panel on the Deck uses for the same two lists:
       a file is Arriving until it lands, then it is Received. Both sides of a
       transfer describing it differently is how someone watching one screen
       and holding the other ends up unsure whether they are looking at the
       same thing. -->
  <h2 id="arrivingHeading" style="display:none">Arriving</h2>
  <ul id="queue"></ul>

  <h2 id="receivedHeading"%(hide)s>Received</h2>
  <ul id="already">%(listed)s</ul>
</main>

<script>
// An absolute path including the token. A relative 'upload/...' would resolve
// against /<token> -- which the browser treats as a file, not a directory -- and
// drop the token, so every upload would be refused.
const UPLOAD_BASE = '/%(token)s/upload/';
// Where to ask how much of a file the Deck already has, for carrying on from an
// upload that was cut off. Same token, same reason it is absolute.
const PENDING_BASE = '/%(token)s/pending/';
%(script)s
</script>
</body></html>""" % {
        "dir": html.escape(directory or "?"),
        "token": token,
        "listed": listed,
        "hide": "" if arrived else ' style="display:none"',
        "keep": _BOOKMARK_HINT if durable else "",
        # The report is reached by its own address, which a camera gets from the
        # QR code. Somebody who came the other way -- short address, six digits
        # -- lands here instead, so the door has to be on this page too or the
        # keyboard route reaches everything except the thing they came for.
        # A button beside the heading rather than a line of text under it.
        # This page is a place you were sent to do one thing -- send files -- and
        # the report is the other reason somebody is here at all, so it belongs
        # where a second action belongs: on the header row, out of the way of the
        # thing the page is for, and not dressed up as prose to be read past.
        "report": (
            '    <a class="report" href="/%s/report">Diagnostic report</a>' % token
        ) if report else "",
        "style": _STYLE,
        "script": _SCRIPT,
        "icon": _FAVICON,
    }
