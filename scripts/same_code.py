"""Check that files changed only in their comments and docstrings.

    python scripts/same_code.py [REV]

Compares every changed .py, .ts and .tsx file with its version at REV
(default HEAD) once comments and docstrings are taken out: Python by its
syntax tree, TypeScript by its tokens. Prints each file whose code differs
and exits 1, so a comment-only pass can be shown to be one.
"""

import ast
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Tokens of a TypeScript source without its comments, by the compiler's own
# scanner, one JSON array per file read from stdin.
TS_TOKENS = r"""
const ts = require("typescript");
let src = "";
process.stdin.on("data", (d) => (src += d)).on("end", () => {
  const scanner = ts.createScanner(ts.ScriptTarget.Latest, true, ts.LanguageVariant.JSX, src);
  const out = [];
  for (let k = scanner.scan(); k !== ts.SyntaxKind.EndOfFileToken; k = scanner.scan()) {
    out.push(scanner.getTokenText());
  }
  process.stdout.write(JSON.stringify(out));
});
"""


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout


def py_shape(source):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) \
                and isinstance(getattr(body[0], "value", None), ast.Constant) \
                and isinstance(body[0].value.value, str):
            node.body = body[1:] or [ast.Pass()]
    return ast.dump(tree, include_attributes=False)


def ts_shape(source):
    done = subprocess.run(["node", "-e", TS_TOKENS], cwd=ROOT, input=source,
                          capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(done.stdout)


def main():
    rev = sys.argv[1] if len(sys.argv) > 1 else "HEAD"
    changed = [f for f in git("diff", "--name-only", rev).split()
               if f.endswith((".py", ".ts", ".tsx")) and os.path.exists(os.path.join(ROOT, f))]
    bad = []
    for path in changed:
        try:
            before = git("show", "%s:%s" % (rev, path))
        except subprocess.CalledProcessError:
            continue  # new file: nothing to compare with
        with open(os.path.join(ROOT, path), encoding="utf-8") as handle:
            after = handle.read()
        shape = py_shape if path.endswith(".py") else ts_shape
        if shape(before) != shape(after):
            bad.append(path)
    for path in bad:
        print("code changed:", path)
    print("%d file(s) checked, %d with code changes" % (len(changed), len(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
