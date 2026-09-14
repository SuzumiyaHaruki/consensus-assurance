import re

SAFE_MODULES = {"Naturals", "Integers", "Sequences", "FiniteSets", "Bags", "Reals", "Behavior"}


def tla_code(source):
    """Remove strings and nested comments while preserving line structure for validation."""
    out, i, depth, quoted = [], 0, 0, False
    while i < len(source):
        pair = source[i:i+2]
        c = source[i]
        if depth:
            if pair == "(*": depth += 1; out.extend("  "); i += 2; continue
            if pair == "*)": depth -= 1; out.extend("  "); i += 2; continue
            out.append("\n" if c == "\n" else " "); i += 1; continue
        if quoted:
            if ord(c) == 92 and i+1<len(source): out.extend("  "); i += 2; continue
            if c == '"': quoted=False
            out.append("\n" if c == "\n" else " "); i += 1; continue
        if pair == "(*": depth=1; out.extend("  "); i += 2; continue
        if pair == "\\*":
            end=source.find("\n",i)
            if end<0: end=len(source)
            out.extend(" "*(end-i)); i=end; continue
        if c == '"': quoted=True; out.append(" "); i += 1; continue
        out.append(c); i += 1
    if depth or quoted: raise ValueError("Unterminated TLA comment or string")
    return "".join(out)


def validate_tla(source, module):
    code = tla_code(source)
    if not re.search(r"-+ MODULE " + module + r" -+", code):
        raise ValueError("Unexpected TLA module name")
    if re.search(r"\b(?:INSTANCE|LOCAL|ASSUME|Java|IOUtils|Json|CSV)\b",code):
        raise ValueError("Unsupported module feature; external overrides and assumptions are not accepted")
    if re.search(r"\b[A-Za-z_]\w*\s*!\s*[A-Za-z_]\w*",code) or re.search(r"!(?!\s*[\[.])",code):
        raise ValueError("Module-qualified operators are not allowed; EXCEPT updates are supported")
    for match in re.finditer(r"\bEXTENDS\s+([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)",code):
        modules = {m.strip() for m in match[1].split(",")}
        if not modules <= SAFE_MODULES: raise ValueError("Unapproved TLA module dependency")
