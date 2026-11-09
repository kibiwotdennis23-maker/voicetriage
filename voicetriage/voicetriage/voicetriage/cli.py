"""Command line tools: validate, scaffold, sheet, simulate, serve.

    python -m voicetriage validate
    python -m voicetriage scaffold ki "Kikuyu"
    python -m voicetriage sheet kln > kalenjin_recording_sheet.csv
    python -m voicetriage simulate --lang sw
    python -m voicetriage serve --dev
"""
from __future__ import annotations

import argparse
import sys

from .engine import Tree
from .facilities import Directory
from .languages import LANG_DIR, load_packs, recording_sheet, required_keys, scaffold_pack


def _load():
    tree, directory = Tree.load(), Directory.load()
    return tree, directory, load_packs(LANG_DIR), required_keys(tree, directory)


def cmd_validate(_args) -> int:
    tree, _directory, packs, required = _load()
    problems = tree.validate()
    print(f"Triage tree v{tree.data.get('version')}: " + ("OK" if not problems else "PROBLEMS"))
    for problem in problems:
        print("  -", problem)
    if not problems:
        print(f"  longest path: {tree.max_questions()} questions, {len(list(tree.iter_paths()))} routes")
        print(f"  status: {tree.data.get('status')}")
    print("\nLanguage packs:")
    for pack in sorted(packs.values(), key=lambda p: p.order):
        missing, bad_audio = pack.missing(required), pack.audio_problems()
        state = "ready" if not missing and not bad_audio else f"{len(missing)} prompts missing"
        print(f"  {pack.code:<6} {pack.name:<12} {state}; reviewed={pack.reviewed}")
        if bad_audio:
            print(f"         audio files not found for: {', '.join(bad_audio)}")
    return 1 if problems else 0


def cmd_scaffold(args) -> int:
    _tree, _directory, _packs, required = _load()
    folder = scaffold_pack(args.code, args.name, LANG_DIR, required)
    print(f"Created {folder}/pack.json with {len(required)} empty prompts.")
    print(f"Next: python -m voicetriage sheet {args.code} > {args.code}_sheet.csv")
    return 0


def cmd_sheet(args) -> int:
    _tree, _directory, packs, required = _load()
    if args.code not in packs:
        print(f"No pack {args.code!r}. Run scaffold first.", file=sys.stderr)
        return 1
    sys.stdout.write(recording_sheet(packs[args.code], packs.get("en"), required))
    return 0


def cmd_simulate(args) -> int:
    """Walk the call flow in the terminal, with no phone or telephony account needed."""
    tree, _directory, packs, required = _load()
    pack = packs.get(args.lang)
    if pack is None or not pack.is_ready(required):
        print(f"Language {args.lang!r} is not ready. Run: python -m voicetriage validate", file=sys.stderr)
        return 1
    node_id, trail = tree.start, []
    while not tree.is_outcome(node_id):
        print("\n" + pack.text(node_id))
        node = tree.node(node_id)
        if node["type"] == "yesno":
            print(pack.text("yes_no_hint"))
            keys = {"1": "yes", "2": "no"}
        else:
            keys = {k: k for k in node["options"]}
        pressed = input("> ").strip()
        if pressed not in keys:
            print(pack.text("invalid"))
            continue
        trail.append((node_id, keys[pressed]))
        node_id = tree.next_node(node_id, keys[pressed])
    summary = tree.summarize(trail, node_id)
    print("\n" + pack.text(node_id))
    print(f"\n[clinic would see] {summary['level'].replace('_', ' ').upper()} | {summary['group']} | "
          f"{'; '.join(summary['reported']) or 'no danger signs reported'}")
    return 0


def cmd_serve(args) -> int:
    from .app import create_app

    overrides = {}
    if args.dev:
        overrides = {"TOKENS": {"dev-token": "*"}, "SMS_MODE": "dry_run"}
        print("Dev mode: dashboard token is 'dev-token'; SMS are logged, not sent.")
    app = create_app(overrides)
    app.run(host=args.host, port=args.port, debug=False)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="voicetriage", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate", help="check the triage tree and every language pack").set_defaults(fn=cmd_validate)
    p = sub.add_parser("scaffold", help="create an empty language pack")
    p.add_argument("code")
    p.add_argument("name")
    p.set_defaults(fn=cmd_scaffold)
    p = sub.add_parser("sheet", help="print a CSV recording/translation sheet for a language")
    p.add_argument("code")
    p.set_defaults(fn=cmd_sheet)
    p = sub.add_parser("simulate", help="try the triage in the terminal")
    p.add_argument("--lang", default="en")
    p.set_defaults(fn=cmd_simulate)
    p = sub.add_parser("serve", help="run the development server")
    p.add_argument("--dev", action="store_true")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=5000)
    p.set_defaults(fn=cmd_serve)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
