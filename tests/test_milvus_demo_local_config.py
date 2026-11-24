"""Verify the personal credential launcher with no actual secret or service call."""
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import logging
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless
from unittest.mock import Mock, patch

import milvus_public_demo as cli
from services.milvus_public_demo import DemoError, QUESTION, SOURCE


DUMMY = "DUMMY_ONLY_NOT_A_CLOUD_KEY"
SAMPLE = {"endpoint": "https://in03-0123456789abcde.serverless.gcp-us-west1.cloud.zilliz.com",
          "collection": "reviewed_shared_collection", "token": DUMMY}


class MilvusLocalConfigTests(TestCase):
    def setUp(self):
        dest = TemporaryDirectory()
        self.addCleanup(dest.cleanup)
        self.home = Path(dest.name).resolve()
        self.folder = self.home / ".agriagent"
        self.folder.mkdir(mode=0o700)
        self.secret = self.folder / "milvus-demo.json"
        self.old_logging = logging.getLogger().manager.disable
        self.addCleanup(logging.disable, self.old_logging)
        home = patch("milvus_public_demo.Path.home", return_value=self.home)
        home.start()
        self.addCleanup(home.stop)

    def save(self, text=None):
        self.secret.write_text(json.dumps(SAMPLE) if text is None else text, encoding="utf-8")
        if os.name == "posix":
            self.secret.chmod(0o600)

    def test_serve_reads_fresh_token_only_once_and_forces_read_only(self):
        self.save()
        app = Mock()
        out = StringIO()
        getpass = Mock(side_effect=AssertionError("No credential prompt"))
        with patch("data_api.create_app", return_value=app) as create, redirect_stdout(out):
            self.assertEqual(cli.main(["serve", "--local-config"], token_reader=getpass), 0)
        demo = create.call_args.kwargs["viva_milvus_chat"]
        self.assertTrue(demo.target.shared_read_only)
        self.assertFalse(demo._allow_collection_load)
        self.assertEqual(demo.target.collection, SAMPLE["collection"])
        self.assertEqual(demo._token, DUMMY)
        self.assertNotIn(DUMMY, out.getvalue())
        app.run.assert_called_once_with(host="127.0.0.1", port=5008, debug=False, use_reloader=False)
        getpass.assert_not_called()
        fresh = {**SAMPLE, "token": "fresh-test-token"}
        self.save(json.dumps(fresh))
        self.assertEqual(cli._local_config()[1], fresh["token"])

    def test_local_config_seeded_layout_returns_public_quote_without_cloud_management(self):
        seeded = "agriagent_demo_0123456789ab"
        self.save(json.dumps({**SAMPLE, "collection": seeded}))
        provider, embedder, model = Mock(), Mock(), Mock()
        provider.has_collection.return_value = True
        embedder.embed_query.return_value = [0.03125] * 1024
        model.invoke.return_value.content = "This corridor comprises 13 districts of Bihar. [1]"
        with (patch("data_api.create_app") as create, redirect_stdout(StringIO()),
              patch("services.milvus_public_demo._connect", return_value=provider),
              patch("services.milvus_public_demo._LoopbackEmbedder", return_value=embedder),
              patch("services.milvus_public_demo._LoopbackChat", return_value=model)):
            self.assertEqual(cli.main(["serve", "--local-config"]), 0)
        demo = create.call_args.kwargs["viva_milvus_chat"]
        self.assertFalse(demo.target.shared_read_only)
        text = demo._rows[14, 0]
        provider.search.return_value = [[{"entity": {
            "source": SOURCE, "text_content": text, "metadata": {"page_number": 14, "chunk_index": 0},
        }}]]
        answer = demo.ask(QUESTION, "en")
        self.assertEqual(answer["records"][0]["content"], text)
        self.assertEqual(answer["document_chat"]["status"], "cited")
        self.assertEqual([method for method, _, _ in provider.method_calls],
                         ["has_collection", "search", "close"])
        self.assertEqual(provider.search.call_args.args, (seeded,))
        self.assertNotIn("mongo_collection", provider.search.call_args.kwargs["filter"])

    def test_preview_seed_and_normal_cli_never_read_profile_secret(self):
        getpass = Mock()
        with (patch("milvus_public_demo._local_config", side_effect=AssertionError("config read")),
              redirect_stdout(StringIO()), redirect_stderr(StringIO())):
            self.assertEqual(cli.main([], token_reader=getpass), 0)
            self.assertEqual(cli.main(["preview", "--local-config"], token_reader=getpass), 1)
            self.assertEqual(cli.main(["seed", "--local-config"], token_reader=getpass), 1)
            self.assertEqual(cli.main(["ask", "--local-config"], token_reader=getpass), 1)
            self.assertEqual(cli.main(["serve", "--local-config", "--endpoint", SAMPLE["endpoint"]],
                                      token_reader=getpass), 1)
            self.assertEqual(cli.main(["serve", "--local-config", "--approve-public-upload"],
                                      token_reader=getpass), 1)
            self.assertEqual(cli.main(["serve"], token_reader=getpass), 1)
        getpass.assert_not_called()

    def test_missing_and_invalid_config_fail_without_logging_values_or_launching(self):
        fallback = Mock()
        for text in (None, "garbage " + DUMMY, json.dumps({**SAMPLE, "token": "bad secret"}),
                     json.dumps({**SAMPLE, "write": True}),
                     json.dumps(SAMPLE).replace('"token"', '"token":"a","token"')):
            if text is not None:
                self.save(text)
            output, errors = StringIO(), StringIO()
            with (patch("data_api.create_app") as app, redirect_stdout(output), redirect_stderr(errors)):
                self.assertEqual(cli.main(["serve", "--local-config"], token_reader=fallback), 1)
            app.assert_not_called()
            self.assertNotIn(DUMMY, output.getvalue() + errors.getvalue())
        fallback.assert_not_called()

    def test_personal_file_under_this_repo_or_any_git_repo_is_rejected(self):
        self.save()
        with patch("milvus_public_demo._REPOSITORY_ROOT", self.home), self.assertRaisesRegex(DemoError, "outside Git"):
            cli._local_config()
        (self.home / ".git").mkdir()
        (self.home / ".git" / "HEAD").write_text("ref: refs/heads/main", encoding="ascii")
        with self.assertRaisesRegex(DemoError, "outside Git"):
            cli._local_config()

    @skipUnless(os.name == "posix", "POSIX ownership/mode and links")
    def test_shared_permissions_symlink_and_hardlink_are_rejected(self):
        self.save()
        self.secret.chmod(0o644)
        with self.assertRaisesRegex(DemoError, "chmod 600"):
            cli._local_config()
        self.secret.chmod(0o600)
        moved = self.folder / "elsewhere.json"
        self.secret.rename(moved)
        self.secret.symlink_to(moved)
        with self.assertRaisesRegex(DemoError, "symbolic link"):
            cli._local_config()
        self.secret.unlink()
        os.link(moved, self.secret)
        with self.assertRaisesRegex(DemoError, "unlinked"):
            cli._local_config()
