"""Preview, seed, or run the opt-in public-report Milvus dashboard."""
import argparse
from getpass import GetPassWarning, getpass
import logging
from secrets import token_hex
import sys
import warnings

from services.milvus_public_demo import (
    DemoError, PublicMilvusDemo, QUESTION, REVIEWED_SHA256, SOURCE, Target, public_passages, seed,
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


def main(argv=None, *, token_reader=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preview", "seed", "ask", "serve"), nargs="?", default="preview")
    parser.add_argument("--endpoint", help="Approved HTTPS Zilliz cluster endpoint (never an authentication URL)")
    parser.add_argument("--collection")
    parser.add_argument("--shared-read-only", action="store_true", help="Explicitly use an approved already-loaded collection")
    parser.add_argument("--approve-public-upload", action="store_true", help="Seed only the reviewed public report in a new demo collection")
    parser.add_argument("--show-passages", action="store_true", help="Print exact outbound source text in preview")
    parser.add_argument("--port", type=int, default=5008, help="Loopback dashboard port (serve only)")
    args = parser.parse_args(argv)
    try:
        public = public_passages()
        if args.command == "preview":
            print(f"Local preview only: {len(public)} reviewed public passages; no service contacted.")
            print(f"Public report: {SOURCE}\nPassage SHA-256: {REVIEWED_SHA256}")
            print(f"Suggested fresh demo collection: agriagent_demo_{token_hex(6)}")
            if args.show_passages:
                for (page, chunk), text in sorted(public.items()):
                    print(f"\n[PDF page {page}, chunk {chunk}]\n{text}")
            return 0
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
        token = (token_reader or _token)()
        if args.command == "seed":
            count = seed(target, token, public)
            print(f"Zilliz confirmed {count} public passages in {target.collection}. No MongoDB sync was run.")
        else:
            demo = PublicMilvusDemo(target, token, rows=public)
            if args.command == "ask":
                answer = demo.ask(QUESTION, "en")
                print(answer["answer"])
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
