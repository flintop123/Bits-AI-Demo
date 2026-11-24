"""Preview, seed, or run the opt-in public-report Milvus dashboard."""
import argparse
import json
from getpass import GetPassWarning, getpass
import logging
import os
from pathlib import Path
import re
from secrets import token_hex
import stat
import sys
import warnings

from services.milvus_public_demo import (
    DEMO_COLLECTION, DemoError, PublicMilvusDemo, QUESTION, REVIEWED_SHA256, SOURCE, Target, public_passages, seed,
)


def _token():
    if not sys.stdin.isatty():
        raise DemoError("Use an interactive terminal for hidden token entry.")
    with warnings.catch_warnings():
        warnings.simplefilter("error", GetPassWarning)
        try:
            result = getpass("Approved Zilliz token (hidden): ").strip()
        except (GetPassWarning, EOFError):
            raise DemoError("Hidden token entry was unavailable; no connection made.") from None
    if not result:
        raise DemoError("The token was empty; no connection made.")
    return result


_REPOSITORY_ROOT = Path(__file__).resolve().parent
_CONFIG_NAME = "milvus-demo.json"
_MAX_CONFIG_BYTES = 16_384


def _config_pairs(pairs):
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise DemoError("Remove duplicate fields from the personal Milvus config.")
    return fields


def _local_config():
    """Read the current account's separate file; never consult repo config or env tokens."""
    try:
        home = Path.home().resolve(strict=True)
        if os.name == "nt" and str(home).startswith("\\\\"):
            raise DemoError("The personal Milvus config must be on this computer, not a network share.")
        folder = home / ".agriagent"
        file = folder / _CONFIG_NAME
        if folder.is_symlink() or file.is_symlink():
            raise DemoError("The personal Milvus config cannot be a symbolic link.")
        resolved = file.resolve(strict=True)
        git_markers = (parent / ".git" for parent in resolved.parents)
        if (resolved != file or resolved.is_relative_to(_REPOSITORY_ROOT)
                or any(marker.is_file() or (marker / "HEAD").is_file() for marker in git_markers)):
            raise DemoError("Keep the personal Milvus config outside Git and do not link it.")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        flags |= getattr(os, "O_BINARY", 0)
        with os.fdopen(os.open(resolved, flags), "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise DemoError("Use a regular, unlinked personal Milvus config file.")
            if os.name == "posix" and (info.st_uid != os.getuid() or info.st_mode & 0o077):
                raise DemoError("The personal Milvus config must belong to you and use chmod 600.")
            raw = stream.read(_MAX_CONFIG_BYTES + 1)
        if len(raw) > _MAX_CONFIG_BYTES:
            raise DemoError("The personal Milvus config is too large.")
        payload = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_config_pairs)
    except DemoError:
        raise
    except (OSError, RuntimeError, ValueError):
        raise DemoError(
            "Could not read ~/.agriagent/milvus-demo.json. Check that it exists and contains valid UTF-8 JSON."
        ) from None
    if (not isinstance(payload, dict) or set(payload) != {"endpoint", "collection", "token"}
            or any(not isinstance(value, str) for value in payload.values())):
        raise DemoError("The personal Milvus config needs exactly three string fields: endpoint, collection, token.")
    token = payload["token"]
    if not 1 <= len(token) <= 4096 or re.search(r"[\x00-\x20\x7f]", token):
        raise DemoError("The personal Milvus config needs a nonempty approved token, without spaces.")
    collection = payload["collection"]
    seeded_layout = bool(DEMO_COLLECTION.fullmatch(collection))
    if collection.startswith("agriagent_demo_") and not seeded_layout:
        raise DemoError("For a seeded collection, use the exact agriagent_demo_<12 hex> name.")
    # shared_read_only selects the teammate's legacy row format. Independently,
    # the saved-credential launcher forbids load or other management operations.
    return Target(payload["endpoint"], collection, shared_read_only=not seeded_layout), token


def main(argv=None, *, token_reader=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preview", "seed", "ask", "serve"), nargs="?", default="preview")
    parser.add_argument("--endpoint", help="Approved HTTPS Zilliz cluster endpoint (never an authentication URL)")
    parser.add_argument("--collection")
    parser.add_argument("--shared-read-only", action="store_true", help="Explicitly use an approved already-loaded collection")
    parser.add_argument("--approve-public-upload", action="store_true", help="Seed only the reviewed public report in a new demo collection")
    parser.add_argument("--show-passages", action="store_true", help="Print exact outbound source text in preview")
    parser.add_argument("--port", type=int, default=5008, help="Loopback dashboard port (serve only)")
    parser.add_argument("--local-config", action="store_true",
                        help="For serve only: read ~/.agriagent/milvus-demo.json with a read-only collection connection")
    args = parser.parse_args(argv)
    try:
        if args.local_config and (
            args.command != "serve" or args.endpoint is not None or args.collection is not None
            or args.shared_read_only or args.approve_public_upload
        ):
            raise DemoError("Use --local-config only with serve and without other connection or write flags.")
        public = public_passages()
        if args.command == "preview":
            print(f"Local preview only: {len(public)} reviewed public passages; no service contacted.")
            print(f"Public report: {SOURCE}\nPassage SHA-256: {REVIEWED_SHA256}")
            print(f"Suggested fresh demo collection: agriagent_demo_{token_hex(6)}")
            if args.show_passages:
                for (page, chunk), text in sorted(public.items()):
                    print(f"\n[PDF page {page}, chunk {chunk}]\n{text}")
            return 0
        if not args.local_config:
            if not args.endpoint or not args.collection:
                raise DemoError("Supply an explicit --endpoint and --collection; no default credentials or collection are used.")
            target = Target(args.endpoint, args.collection, args.shared_read_only)
        if args.command == "seed" and (args.shared_read_only or not args.approve_public_upload):
            raise DemoError("Seeding requires --approve-public-upload and a new demo collection, never a shared collection.")
        if args.approve_public_upload and args.command != "seed":
            raise DemoError("--approve-public-upload is only valid for the independent seed command.")
        if args.command == "serve" and not 1024 <= args.port <= 65535:
            raise DemoError("Choose a dashboard port from 1024 to 65535.")
        if args.command == "seed":
            print(f"You are authorizing upload of {len(public)} public passages and their vectors to {target.collection}.")
        # Prevent dependency exception logging from printing any provider data.
        logging.disable(logging.CRITICAL)
        if args.local_config:
            target, token = _local_config()
        else:
            token = (token_reader or _token)()
        if args.command == "seed":
            count = seed(target, token, public)
            print(f"Zilliz confirmed {count} public passages in {target.collection}. No MongoDB sync was run.")
        else:
            demo = PublicMilvusDemo(target, token, rows=public, allow_collection_load=not args.local_config)
            if args.command == "ask":
                answer = demo.ask(QUESTION, "en")
                print(answer["answer"])
                print("Generation check:", answer["document_chat"]["generation"])
                for row in answer["records"]:
                    print(f"\n[{row['citation_id']}] {row['source']}#page={row['page_number']} "
                          f"(chunk {row['chunk_index']})\n{row['content']}")
            else:
                from data_api import create_app
                app = create_app(viva_milvus_chat=demo)
                print(f"Open http://127.0.0.1:{args.port}/ and choose Ask AgriAgent, then Milvus Vector RAG.")
                app.run(host="127.0.0.1", port=args.port, debug=False, use_reloader=False)
    except DemoError as error:
        print(error, file=sys.stderr)
        return 1
    except Exception as error:
        print(f"Milvus demo did not complete ({type(error).__name__}); check the approved settings and local models.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
