#!/usr/bin/env python3
"""hamster rules CLI — the deterministic half of the loop.

  rules.py list [--json]              every rule with scope, action, fires, last
  rules.py test [id]                  run keep-tests; exit 1 on any failure or invalid file
  rules.py add <file.json> [--scope user|project] [--force]
                                      validate + run tests, then install (refuses on red)
  rules.py check <tool> <input>       dry-run: which rules fire on this input
  rules.py prune [--days 60] [--json] user/project rules created >= N days ago with zero fires (defaults and keep:true exempt)
  rules.py rm <id>                    delete a user/project rule file (never default)
"""
import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "hooks"))
from _rules import (  # noqa: E402
    evaluate,
    is_tested,
    iter_rules,
    load_fires,
    load_rules,
    prunable,
    rule_dirs,
    run_tests,
    validate,
)


def cmd_list(args):
    rules = load_rules()
    fires = load_fires()
    rows = []
    for r in iter_rules(rules):
        f = fires.get(r["id"]) or {}
        rows.append(
            {
                "id": r["id"],
                "scope": r["_scope"],
                "action": r["action"],
                "effective": r["_effective"],
                "tested": not r["_untested"],
                "fires": f.get("count", 0),
                "last": f.get("last", ""),
                "created": r.get("created", ""),
                "source": r.get("source", ""),
                "path": r["_path"],
            }
        )
    if args.json:
        print(json.dumps({"rules": rows, "errors": rules["_errors"]}, indent=2))
        return 0
    if not rows:
        print("no rules")
    for row in rows:
        flag = "" if row["tested"] else "  (untested → warn)"
        print(
            f"{row['id']:<32} {row['scope']:<8} {row['action']:<5} fires={row['fires']:<4} "
            f"last={row['last'][:10] or '-':<10} {row['source']}{flag}"
        )
    for e in rules["_errors"]:
        print(f"INVALID {e}")
    return 0


def _run(rule):
    results = run_tests(rule)
    ok = all(good for _, good in results)
    return ok, results


def cmd_test(args):
    rules = load_rules()
    failed = 0
    for e in rules["_errors"]:
        print(f"INVALID {e}")
        failed += 1
    for r in iter_rules(rules):
        if args.id and r["id"] != args.id:
            continue
        if not is_tested(r):
            print(f"UNTESTED {r['id']}: needs one `block` and one `pass` test (loads as warn)")
            if r["action"] == "block":
                failed += 1
            continue
        ok, results = _run(r)
        print(f"{'ok  ' if ok else 'FAIL'} {r['id']}")
        if not ok:
            failed += 1
            for t, good in results:
                if not good:
                    print(f"       expected {t['expect']} for: {t['input']!r}")
    return 1 if failed else 0


def cmd_add(args):
    src = Path(args.file)
    try:
        rule = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"cannot read {src}: {e}")
        return 1
    probs = validate(rule)
    if probs:
        print("invalid rule: " + "; ".join(probs))
        return 1
    if not is_tested(rule) and rule["action"] == "block":
        print("refused: a `block` rule needs one test expecting block and one expecting pass")
        return 1
    ok, results = _run(rule)
    if not ok:
        for t, good in results:
            if not good:
                print(f"FAIL expected {t['expect']} for: {t['input']!r}")
        return 1
    dest_dir = dict(rule_dirs()).get(args.scope)
    if dest_dir is None:
        print(f"no {args.scope} rule dir here (project scope needs a git work tree)")
        return 1
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{rule['id']}.json"
    existing = load_rules()
    if rule["id"] in existing and not args.force:
        print(f"refused: id `{rule['id']}` exists at {existing[rule['id']]['_path']} (use --force)")
        return 1
    rule.setdefault("created", datetime.now(timezone.utc).date().isoformat())
    dest.write_text(json.dumps(rule, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"installed {dest} ({len(rule['tests'])} tests green)")
    return 0


def cmd_check(args):
    field = "command" if args.tool == "Bash" else args.field
    rules = load_rules()
    hits = evaluate(rules, args.tool, {field: args.input})
    gated = [r["id"] for r in iter_rules(rules) if r.get("when")]
    if gated:
        print(f"(when-gated rules evaluated against this cwd/branch: {', '.join(gated)})")
    if not hits:
        print("no rule fires")
        return 0
    for r, action in hits:
        print(f"{action:<5} {r['id']}: {r['message']}")
    return 0


def cmd_prune(args):
    rules = load_rules()
    fires = load_fires()
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    out = []
    for r in iter_rules(rules):
        if not prunable(r):
            continue
        try:
            created = datetime.fromisoformat(r.get("created", "")).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if created < cutoff and not (fires.get(r["id"]) or {}).get("count"):
            out.append({"id": r["id"], "scope": r["_scope"], "created": r.get("created"), "path": r["_path"]})
    if args.json:
        print(json.dumps(out, indent=2))
    elif not out:
        print(f"nothing to prune: every rule older than {args.days}d has fired")
    else:
        print(f"never fired, created >= {args.days}d ago (delete with `rules.py rm <id>`):")
        for o in out:
            print(f"  {o['id']:<32} {o['scope']:<8} created {o['created']}")
    return 0


def cmd_rm(args):
    rules = load_rules()
    r = rules.get(args.id)
    if not r:
        print(f"no rule `{args.id}`")
        return 1
    if r["_scope"] == "default":
        print("refused: bundled default rules are removed by uninstalling, not rm")
        return 1
    os.remove(r["_path"])
    print(f"removed {r['_path']}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="rules.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("list"); s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_list)
    s = sub.add_parser("test"); s.add_argument("id", nargs="?"); s.set_defaults(fn=cmd_test)
    s = sub.add_parser("add"); s.add_argument("file"); s.add_argument("--scope", default="user", choices=("user", "project")); s.add_argument("--force", action="store_true"); s.set_defaults(fn=cmd_add)
    s = sub.add_parser("check"); s.add_argument("tool"); s.add_argument("input"); s.add_argument("--field", default="file_path"); s.set_defaults(fn=cmd_check)
    s = sub.add_parser("prune"); s.add_argument("--days", type=int, default=60); s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_prune)
    s = sub.add_parser("rm"); s.add_argument("id"); s.set_defaults(fn=cmd_rm)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
