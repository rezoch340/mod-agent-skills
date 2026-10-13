"""Relay regression tests: in-memory HTTP and filesystem doubles, no network or scratch."""

import copy
from contextlib import contextmanager, ExitStack
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace
import unittest
from unittest import mock
import urllib.error
import urllib.request
import urllib.response
from email.message import Message


SCRIPT = Path(__file__).resolve().parents[1] / "mod-dispatch" / "scripts" / "relay.py"
SPEC = importlib.util.spec_from_file_location("codex_relay", SCRIPT)
relay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(relay)


def configured():
    config = copy.deepcopy(relay.DEFAULT_CONFIG)
    config.update(
        base_url="https://relay.example/v1",
        api_key="test-secret-never-print",
        models={role: "model-" + role for role in ("read", "write", "brain", "review")},
    )
    return config


def completion(content="Reviewed successfully", finish_reason="stop", **message_fields):
    return {
        "choices": [{
            "finish_reason": finish_reason,
            "message": {"role": "assistant", "content": content, **message_fields},
        }],
    }


def response_bytes(raw):
    response = io.BytesIO(raw)
    response.status = 200
    return response


@contextmanager
def memory_workspace(contents=None, symlinks=None, mode=stat.S_IFREG | 0o600):
    """Model attachment bytes and resolved paths without touching disk."""
    contents = {str(Path("/workspace") / name): value for name, value in (contents or {}).items()}
    symlinks = symlinks or {}
    opened = []
    descriptors = {}

    class MemoryFile(io.BytesIO):
        def fileno(self):
            return 123

    def resolve(path, strict=False):
        return Path(symlinks.get(str(path), os.path.normpath(str(path))))

    def open_file(path, flags, *args):
        name = str(path)
        if name not in contents:
            raise FileNotFoundError(name)
        opened.append(name)
        fd = 100 + len(opened)
        descriptors[fd] = contents[name]
        return fd

    with ExitStack() as stack:
        stack.enter_context(mock.patch.object(Path, "is_dir", return_value=True))
        stack.enter_context(mock.patch.object(Path, "resolve", resolve))
        stack.enter_context(mock.patch.object(relay.os, "open", side_effect=open_file))
        stack.enter_context(mock.patch.object(relay.os, "fdopen", side_effect=lambda fd, mode: MemoryFile(descriptors[fd])))
        stack.enter_context(mock.patch.object(relay.os, "fstat", return_value=SimpleNamespace(st_mode=mode)))
        yield opened


class ConfigTests(unittest.TestCase):
    def test_changing_endpoint_requires_replacement_key(self):
        original = configured()
        before = copy.deepcopy(original)
        with self.assertRaises(relay.RelayError):
            relay.update_config(original, {"base_url": "https://different.example/v1"})
        self.assertEqual(original, before)

    def test_explicit_key_clear_prevents_requests_to_new_endpoint(self):
        updated = relay.update_config(configured(), {
            "base_url": "https://different.example/v1", "api_key": "",
        })
        with mock.patch.object(urllib.request, "build_opener") as opener:
            with self.assertRaises(relay.RelayError):
                relay.request_json(updated, "/models")
        opener.assert_not_called()

    def test_endpoint_and_key_can_be_updated_together(self):
        updated = relay.update_config(configured(), {
            "base_url": "https://different.example/v1/", "api_key": "replacement-key",
        })
        self.assertEqual(updated["base_url"].rstrip("/"), "https://different.example/v1")
        self.assertEqual(updated["api_key"], "replacement-key")
        self.assertEqual(updated["models"], configured()["models"])

    def test_role_update_preserves_other_mappings(self):
        updated = relay.update_config(configured(), {"models": {"read": "new-reader"}})
        self.assertEqual(updated["models"]["read"], "new-reader")
        for role in ("write", "brain", "review"):
            self.assertEqual(updated["models"][role], configured()["models"][role])


class TransportTests(unittest.TestCase):
    def test_post_has_selected_payload_and_authorization(self):
        payload = {"model": "example-model", "messages": [{"role": "user", "content": "hello"}]}
        response = response_bytes(json.dumps(completion()).encode())
        opener = mock.Mock()
        opener.open.return_value = response
        with mock.patch.object(urllib.request, "build_opener", return_value=opener):
            result = relay.request_json(configured(), "/chat/completions", payload, timeout=17)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://relay.example/v1/chat/completions")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-secret-never-print")
        self.assertEqual(json.loads(request.data), payload)
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 17)
        self.assertEqual(result, completion())

    def test_http_error_body_and_reason_do_not_expose_key(self):
        secret = configured()["api_key"]
        error = urllib.error.HTTPError(
            "https://relay.example/v1/models", 401, "rejected " + secret,
            {}, io.BytesIO(json.dumps({"error": "invalid " + secret}).encode()),
        )
        opener = mock.Mock()
        opener.open.side_effect = error
        with mock.patch.object(urllib.request, "build_opener", return_value=opener):
            with self.assertRaises(relay.RelayError) as caught:
                relay.request_json(configured(), "/models")
        self.assertNotIn(secret, str(caught.exception))

    def test_invalid_json_fails_without_echoing_response(self):
        secret = configured()["api_key"]
        opener = mock.Mock()
        opener.open.return_value = response_bytes(("upstream failure " + secret).encode())
        with mock.patch.object(urllib.request, "build_opener", return_value=opener):
            with self.assertRaises(relay.RelayError) as caught:
                relay.request_json(configured(), "/models")
        self.assertNotIn(secret, str(caught.exception))

    def test_timeout_fails_without_retry_or_leaking_reason(self):
        secret = configured()["api_key"]
        opener = mock.Mock()
        opener.open.side_effect = urllib.error.URLError(TimeoutError(secret))
        with mock.patch.object(urllib.request, "build_opener", return_value=opener):
            with self.assertRaises(relay.RelayError) as caught:
                relay.request_json(configured(), "/models")
        self.assertNotIn(secret, str(caught.exception))
        self.assertEqual(opener.open.call_count, 1)

    def test_oversized_response_is_rejected(self):
        opener = mock.Mock()
        opener.open.return_value = response_bytes(b'{"large": "' + b"a" * 100 + b'"}')
        with mock.patch.object(relay, "MAX_RESPONSE_BYTES", 64):
            with mock.patch.object(urllib.request, "build_opener", return_value=opener):
                with self.assertRaises(relay.RelayError):
                    relay.request_json(configured(), "/models")

    def test_redirect_does_not_make_second_request_or_forward_key(self):
        requests = []

        class MemoryHTTPSHandler(urllib.request.HTTPSHandler):
            def https_open(self, request):
                requests.append(request)
                headers = Message()
                headers["Location"] = "https://untrusted.example/collect"
                response = urllib.response.addinfourl(
                    io.BytesIO(b"redirect"), headers, request.full_url, 302,
                )
                response.msg = "Found"
                return response

        build_opener = urllib.request.build_opener

        def memory_opener(*handlers):
            return build_opener(*handlers, MemoryHTTPSHandler())

        with mock.patch.object(urllib.request, "build_opener", side_effect=memory_opener):
            with self.assertRaises(relay.RelayError):
                relay.request_json(configured(), "/models")
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].full_url, "https://relay.example/v1/models")


class AskTests(unittest.TestCase):
    def test_every_role_selects_its_configured_model(self):
        for role in ("read", "write", "brain", "review"):
            with self.subTest(role=role):
                with mock.patch.object(relay, "collect_files", return_value=("task and file", [])):
                    with mock.patch.object(relay, "request_json", return_value=completion()) as request:
                        result = relay.ask(configured(), role, Path("/project"), [], "review this")
                payload = request.call_args.args[2]
                self.assertEqual(payload["model"], "model-" + role)
                self.assertEqual(payload["messages"][-1], {"role": "user", "content": "task and file"})
                self.assertEqual(result["content"], "Reviewed successfully")
                self.assertEqual(result["role"], role)
                self.assertEqual(result["model"], "model-" + role)
                self.assertNotIn("test-secret-never-print", json.dumps(result))

    def test_incomplete_refused_or_tool_responses_are_not_success(self):
        invalid = [
            {}, {"choices": []}, {"choices": [{"message": {}}]},
            completion(finish_reason="length"),
            completion(finish_reason="content_filter"),
            completion(refusal="Cannot comply"),
            completion(tool_calls=[{"id": "call-1", "type": "function"}]),
            completion(function_call={"name": "run_shell", "arguments": "{}"}),
            completion(content=None), completion(content=[{"type": "text", "text": "answer"}]),
        ]
        for response in invalid:
            with self.subTest(response=response):
                with mock.patch.object(relay, "collect_files", return_value=("task", [])):
                    with mock.patch.object(relay, "request_json", return_value=response):
                        with self.assertRaises(relay.RelayError):
                            relay.ask(configured(), "read", Path("/project"), [], "task")


class AttachmentTests(unittest.TestCase):
    def test_exact_text_and_snapshot_are_attached_once(self):
        raw = "print('你好')\n".encode()
        with memory_workspace({"src/main.py": raw}) as opened:
            prompt, snapshots = relay.collect_files(
                Path("/workspace"), ["src/main.py", "src/../src/main.py"], "review",
            )
        self.assertEqual(json.loads(prompt), {
            "task": "review", "files": [{"path": "src/main.py", "content": raw.decode()}],
        })
        self.assertEqual(snapshots, [{"path": "src/main.py", "sha256": hashlib.sha256(raw).hexdigest()}])
        self.assertEqual(opened, ["/workspace/src/main.py"])

    def test_absolute_traversal_and_external_symlink_never_read_files(self):
        for name in ("/outside/secret", "../secret", "linked-secret"):
            with self.subTest(name=name):
                with memory_workspace(symlinks={"/workspace/linked-secret": "/outside/secret"}) as opened:
                    with self.assertRaises(relay.RelayError):
                        relay.collect_files(Path("/workspace"), [name], "review")
                self.assertEqual(opened, [])

    def test_missing_file_fails_instead_of_silently_omitting_it(self):
        with memory_workspace():
            with self.assertRaises(relay.RelayError):
                relay.collect_files(Path("/workspace"), ["missing.txt"], "review")

    def test_binary_and_nonregular_attachments_are_rejected(self):
        for raw in (b"bad\xff", b"text\x00binary"):
            with self.subTest(raw=raw), memory_workspace({"input": raw}):
                with self.assertRaises(relay.RelayError):
                    relay.collect_files(Path("/workspace"), ["input"], "review")
        with memory_workspace({"pipe": b"text"}, mode=stat.S_IFIFO):
            with self.assertRaises(relay.RelayError):
                relay.collect_files(Path("/workspace"), ["pipe"], "review")

    def test_task_limit_counts_utf8_bytes(self):
        with mock.patch.object(relay, "MAX_INPUT_BYTES", 64), memory_workspace():
            with self.assertRaises(relay.RelayError):
                relay.collect_files(Path("/workspace"), [], "界" * 30)

    def test_attachment_limit_is_aggregate_and_does_not_truncate(self):
        with mock.patch.object(relay, "MAX_INPUT_BYTES", 128):
            with memory_workspace({"a": b"a" * 70, "b": b"b" * 70}):
                with self.assertRaises(relay.RelayError):
                    relay.collect_files(Path("/workspace"), ["a", "b"], "x")

    def test_serialized_prompt_limit_includes_json_escaping(self):
        with mock.patch.object(relay, "MAX_INPUT_BYTES", 128):
            with memory_workspace({"a": b"\n" * 70}):
                with self.assertRaises(relay.RelayError):
                    relay.collect_files(Path("/workspace"), ["a"], "x")


class CommandTests(unittest.TestCase):
    def test_init_uses_shared_connection_at_root_of_each_supported_layout(self):
        layouts = (
            ("/repo/mod-agent-skills/codex/mod-dispatch/scripts/relay.py", "/repo/mod-agent-skills/connection.json"),
            ("/home/user/.agents/skills/mod-dispatch/scripts/relay.py", "/home/user/.agents/skills/connection.json"),
        )
        for script_path, expected_config in layouts:
            stdout = io.StringIO()
            with self.subTest(script_path=script_path), ExitStack() as stack:
                stack.enter_context(mock.patch.object(relay, "__file__", script_path))
                stack.enter_context(mock.patch.object(Path, "resolve", lambda path, strict=False: path))
                stack.enter_context(mock.patch.object(Path, "exists", return_value=False))
                stack.enter_context(mock.patch.object(Path, "is_symlink", return_value=False))
                save = stack.enter_context(mock.patch.object(relay, "save_config"))
                stack.enter_context(mock.patch.object(relay.sys, "stdout", stdout))
                status = relay.main(["init"])
            self.assertEqual(status, 0)
            save.assert_called_once_with(Path(expected_config), relay.DEFAULT_CONFIG, exclusive=True)
            self.assertEqual(json.loads(stdout.getvalue())["connection_file"], expected_config)

    def test_explicit_config_overrides_shared_default(self):
        stdout = io.StringIO()
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(relay, "default_config_path", return_value=Path("/default/connection.json")))
            stack.enter_context(mock.patch.object(Path, "exists", return_value=False))
            stack.enter_context(mock.patch.object(Path, "is_symlink", return_value=False))
            save = stack.enter_context(mock.patch.object(relay, "save_config"))
            stack.enter_context(mock.patch.object(relay.sys, "stdout", stdout))
            status = relay.main(["--config", "/explicit/connection.json", "init"])
        self.assertEqual(status, 0)
        save.assert_called_once_with(Path("/explicit/connection.json"), relay.DEFAULT_CONFIG, exclusive=True)
        self.assertEqual(json.loads(stdout.getvalue())["connection_file"], "/explicit/connection.json")

    def test_init_creates_template_once_and_preserves_existing_config(self):
        for exists in (False, True):
            stdout = io.StringIO()
            with self.subTest(exists=exists), ExitStack() as stack:
                stack.enter_context(mock.patch.object(Path, "exists", return_value=exists))
                stack.enter_context(mock.patch.object(Path, "is_symlink", return_value=False))
                stack.enter_context(mock.patch.object(relay, "load_config", return_value=configured()))
                save = stack.enter_context(mock.patch.object(relay, "save_config"))
                stack.enter_context(mock.patch.object(relay.sys, "stdout", stdout))
                status = relay.main(["--config", "/config/connection.json", "init"])
            self.assertEqual(status, 0)
            self.assertEqual(json.loads(stdout.getvalue())["status"], "existing" if exists else "created")
            if exists:
                save.assert_not_called()
            else:
                save.assert_called_once_with(Path("/config/connection.json"), relay.DEFAULT_CONFIG, exclusive=True)

    def test_configure_accepts_stdin_secret_without_printing_it(self):
        updates = {"base_url": "https://different.example/v1", "api_key": "new-stdin-secret"}
        stdout, stderr = io.StringIO(), io.StringIO()
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(Path, "exists", return_value=True))
            stack.enter_context(mock.patch.object(relay, "load_config", return_value=configured()))
            stack.enter_context(mock.patch.object(relay.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(json.dumps(updates).encode()))))
            stack.enter_context(mock.patch.object(relay.sys, "stdout", stdout))
            stack.enter_context(mock.patch.object(relay.sys, "stderr", stderr))
            save = stack.enter_context(mock.patch.object(relay, "save_config"))
            status = relay.main(["--config", "/config/connection.json", "configure"])
        self.assertEqual(status, 0)
        self.assertEqual(save.call_args.args[1]["api_key"], updates["api_key"])
        self.assertEqual(save.call_args.args[1]["base_url"], updates["base_url"])
        self.assertNotIn(updates["api_key"], stdout.getvalue() + stderr.getvalue())
        self.assertEqual(json.loads(stdout.getvalue())["status"], "configured")

    def test_models_reports_missing_roles_without_silently_substituting_models(self):
        stdout = io.StringIO()
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(relay, "load_config", return_value=configured()))
            stack.enter_context(mock.patch.object(relay, "request_json", return_value={
                "data": [{"id": "model-read"}, {"id": "model-read"}, {"id": "unconfigured-model"}],
            }))
            stack.enter_context(mock.patch.object(relay.sys, "stdout", stdout))
            status = relay.main(["--config", "/config/connection.json", "models"])
        self.assertEqual(status, 0)
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["ids"], ["model-read", "unconfigured-model"])
        self.assertEqual(result["models"], configured()["models"])
        self.assertEqual(result["missing_roles"], {
            role: "model-" + role for role in ("write", "brain", "review")
        })
        self.assertNotIn(configured()["api_key"], stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
