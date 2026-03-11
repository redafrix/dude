from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path

from dude.browser import BrowserController
from dude.config import DudeConfig, load_config
from dude.control import send_command
from dude.eval import (
    benchmark_backends,
    build_speaker_profile_report,
    evaluate_fixtures,
    evaluate_pipeline,
    evaluate_speaker_profile,
    record_fixture,
    record_scenario_corpus,
    record_wake_enrollment,
    write_named_report,
)
from dude.logging import configure_logging
from dude.orchestrator import BackendKind, Orchestrator, TaskRequest
from dude.remote_api import RemoteApiServer
from dude.screen import ScreenCaptureController
from dude.service import run_service
from dude.tailscale import TailscaleController
from dude.telegram_bot import build_telegram_service


def _load(path: Path, verbose: bool = False) -> tuple[DudeConfig, logging.Logger]:
    config = load_config(path)
    logger = configure_logging(config.runtime.log_dir, verbose=verbose)
    return config, logger


def _send(config: DudeConfig, command: str) -> int:
    try:
        response = asyncio.run(
            send_command(config.runtime.control_socket_path, {"command": command})
        )
    except (FileNotFoundError, TimeoutError):
        print(
            "Dude service did not respond. Start it with "
            "`python3 -m dude.cli --config configs/default.yaml serve`."
        )
        return 1
    print(json.dumps(response, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dude", description="Dude local-first assistant runtime.")
    parser.add_argument("--config", default="configs/default.yaml", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="Run the Dude service.")
    serve.add_argument("--verbose", action="store_true")
    serve.add_argument("--warmup", action="store_true")

    remote_serve = subparsers.add_parser("remote-serve", help="Run the authenticated HTTP API.")
    remote_serve.add_argument("--verbose", action="store_true")

    telegram_serve = subparsers.add_parser("telegram-serve", help="Run the Telegram transport.")
    telegram_serve.add_argument("--verbose", action="store_true")
    telegram_serve.add_argument("--once", action="store_true")

    tailscale_serve = subparsers.add_parser(
        "tailscale-serve",
        help="Expose the remote API over Tailscale Serve.",
    )
    tailscale_group = tailscale_serve.add_mutually_exclusive_group()
    tailscale_group.add_argument("--status", action="store_true")
    tailscale_group.add_argument("--reset", action="store_true")

    for name in ("arm", "disarm", "status", "shutdown"):
        subparsers.add_parser(name, help=f"{name.title()} the running service.")

    benchmark = subparsers.add_parser("benchmark", help="Run local backend benchmarks.")
    benchmark.add_argument(
        "--fixture",
        type=Path,
        default=None,
        help="Optional WAV fixture for ASR benchmarking.",
    )
    benchmark.add_argument(
        "--text",
        default="Hi, what can I help you with?",
        help="Benchmark text for TTS timing.",
    )
    benchmark.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/results/backend-benchmark.json"),
        help="Output path for the benchmark report.",
    )

    record = subparsers.add_parser(
        "record-fixture",
        help="Record a fixture WAV from the configured microphone.",
    )
    record.add_argument("--seconds", type=float, default=4.0)
    record.add_argument("--output", type=Path, required=True)

    enroll = subparsers.add_parser(
        "record-wake-enrollment",
        help="Record repeated wake-word takes and emit an enrollment manifest.",
    )
    enroll.add_argument("--output-dir", type=Path, required=True)
    enroll.add_argument("--phrase", default="dude")
    enroll.add_argument("--count", type=int, default=12)
    enroll.add_argument("--seconds", type=float, default=1.8)

    speaker_profile = subparsers.add_parser(
        "build-speaker-profile",
        help="Build a speaker verification profile from an enrollment manifest.",
    )
    speaker_profile.add_argument("--manifest", type=Path, required=True)
    speaker_profile.add_argument("--output", type=Path, required=True)
    speaker_profile.add_argument("--threshold", type=float, default=None)

    speaker_eval = subparsers.add_parser(
        "eval-speaker",
        help="Evaluate a speaker profile against a fixture manifest.",
    )
    speaker_eval.add_argument("--manifest", type=Path, required=True)
    speaker_eval.add_argument("--profile", type=Path, default=None)
    speaker_eval.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/results/speaker-eval.json"),
        help="Output path for the speaker evaluation report.",
    )

    corpus = subparsers.add_parser(
        "record-corpus",
        help="Record a guided voice corpus and emit an evaluation manifest.",
    )
    corpus.add_argument("--output-dir", type=Path, required=True)
    corpus.add_argument("--profile", default="m1-core")
    corpus.add_argument("--takes", type=int, default=1)
    corpus.add_argument("--quiet", action="store_true")

    evaluate = subparsers.add_parser(
        "eval-fixtures",
        help="Evaluate a manifest of recorded fixture WAV files.",
    )
    evaluate.add_argument("--manifest", type=Path, required=True)
    evaluate.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/results/fixture-eval.json"),
        help="Output path for the evaluation report.",
    )

    pipeline_eval = subparsers.add_parser(
        "eval-pipeline",
        help="Replay fixture audio through the live voice pipeline.",
    )
    pipeline_eval.add_argument("--manifest", type=Path, required=True)
    pipeline_eval.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/results/pipeline-eval.json"),
        help="Output path for the pipeline evaluation report.",
    )
    pipeline_eval.add_argument(
        "--wake-backend",
        choices=("transcript", "openwakeword"),
        default=None,
        help="Override the configured wake backend for this evaluation run.",
    )
    pipeline_eval.add_argument(
        "--realtime",
        action="store_true",
        help="Replay audio in realtime instead of as fast as possible.",
    )

    task = subparsers.add_parser("task", help="Route a text task through the orchestrator.")
    task.add_argument("--text", required=True, help="Task request text.")
    task.add_argument(
        "--backend",
        choices=("auto", "local", "codex", "gemini"),
        default="auto",
        help="Preferred execution backend.",
    )
    task.add_argument(
        "--auto-approve",
        action="store_true",
        help="Allow execution for requests that would otherwise require approval.",
    )

    audit = subparsers.add_parser("audit", help="Show recent orchestrator tasks.")
    audit.add_argument("--limit", type=int, default=20)

    memory = subparsers.add_parser("memory", help="Inspect or edit stored memory entries.")
    memory_group = memory.add_mutually_exclusive_group(required=True)
    memory_group.add_argument("--list", action="store_true")
    memory_group.add_argument("--note", help="Create a memory note.")
    memory_group.add_argument("--delete", dest="delete_id", help="Delete a memory entry by id.")
    memory_group.add_argument("--clear", action="store_true")
    memory.add_argument("--limit", type=int, default=20)

    approve = subparsers.add_parser("approve", help="Approve a pending orchestrator task.")
    approve_group = approve.add_mutually_exclusive_group(required=True)
    approve_group.add_argument("--task-id")
    approve_group.add_argument("--latest", action="store_true")

    browser = subparsers.add_parser("browser", help="Run a local browser action.")
    browser.add_argument("--url", default=None, help="URL or domain to open.")
    browser.add_argument(
        "--show",
        action="store_true",
        help="Launch a visible browser window instead of headless capture.",
    )
    browser.add_argument(
        "--state",
        action="store_true",
        help="Show the last recorded browser state instead of opening a page.",
    )

    screen = subparsers.add_parser(
        "screen",
        help="Capture the desktop or inspect the last capture.",
    )
    screen_group = screen.add_mutually_exclusive_group(required=True)
    screen_group.add_argument("--screenshot", action="store_true")
    screen_group.add_argument("--record", action="store_true")
    screen_group.add_argument("--state", action="store_true")
    screen.add_argument("--seconds", type=float, default=None)

    subparsers.add_parser("remote-token", help="Show the configured or generated remote API token.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    config_path: Path = args.config

    if args.command == "serve":
        config, logger = _load(config_path, verbose=args.verbose)
        try:
            asyncio.run(run_service(config, logger, warmup=args.warmup))
        except KeyboardInterrupt:
            return 130
        return 0

    if args.command == "remote-serve":
        config, logger = _load(config_path, verbose=args.verbose)
        server = RemoteApiServer(config, logger)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            return 130
        return 0

    if args.command == "telegram-serve":
        config, logger = _load(config_path, verbose=args.verbose)
        service = build_telegram_service(config, logger)
        try:
            if args.once:
                service.poll_once()
                return 0
            while True:
                service.poll_once()
        except KeyboardInterrupt:
            return 130

    if args.command == "tailscale-serve":
        config, logger = _load(config_path)
        del logger
        controller = TailscaleController(config)
        if args.reset:
            result = controller.reset_serve()
        elif args.status:
            result = controller.serve_status()
        else:
            result = controller.serve_remote_api()
        print(
            json.dumps(
                {
                    "command": result.command,
                    "exit_code": result.exit_code,
                    "stdout_text": result.stdout_text,
                    "stderr_text": result.stderr_text,
                    "url": result.url,
                },
                indent=2,
            )
        )
        return 0 if result.exit_code == 0 else 1

    config, logger = _load(config_path)
    if args.command == "benchmark":
        payload = benchmark_backends(
            config,
            logger,
            fixture_path=args.fixture,
            benchmark_text=args.text,
        )
        output_path = write_named_report(args.output, payload)
        print(json.dumps({"benchmark_path": str(output_path), "results": payload}, indent=2))
        return 0

    if args.command == "record-fixture":
        payload = asyncio.run(record_fixture(config, args.output, args.seconds))
        print(json.dumps(payload, indent=2))
        return 0

    if args.command == "record-wake-enrollment":
        payload = asyncio.run(
            record_wake_enrollment(
                config,
                args.output_dir,
                phrase=args.phrase,
                take_count=args.count,
                duration_seconds=args.seconds,
            )
        )
        print(json.dumps(payload, indent=2))
        return 0

    if args.command == "build-speaker-profile":
        payload = build_speaker_profile_report(
            config,
            logger,
            args.manifest,
            args.output,
            threshold=args.threshold,
        )
        print(json.dumps(payload, indent=2))
        return 0

    if args.command == "eval-speaker":
        profile_path = args.profile or config.speaker.profile_path
        if profile_path is None:
            print(
                json.dumps(
                    {
                        "error": "Speaker evaluation requires --profile or speaker.profile_path.",
                    },
                    indent=2,
                )
            )
            return 1
        payload = evaluate_speaker_profile(
            config,
            args.manifest,
            logger,
            profile_path=profile_path,
        )
        output_path = write_named_report(args.output, payload)
        print(json.dumps({"evaluation_path": str(output_path), "results": payload}, indent=2))
        return 0

    if args.command == "record-corpus":
        payload = asyncio.run(
            record_scenario_corpus(
                config,
                args.output_dir,
                profile=args.profile,
                takes_per_prompt=args.takes,
                announce=not args.quiet,
            )
        )
        print(json.dumps(payload, indent=2))
        return 0

    if args.command == "eval-fixtures":
        payload = evaluate_fixtures(config, args.manifest, logger)
        output_path = write_named_report(args.output, payload)
        print(json.dumps({"evaluation_path": str(output_path), "results": payload}, indent=2))
        return 0

    if args.command == "eval-pipeline":
        payload = asyncio.run(
            evaluate_pipeline(
                config,
                args.manifest,
                logger,
                wake_backend=args.wake_backend,
                realtime=args.realtime,
            )
        )
        output_path = write_named_report(args.output, payload)
        print(json.dumps({"evaluation_path": str(output_path), "results": payload}, indent=2))
        return 0

    if args.command == "task":
        orchestrator = Orchestrator(config, logger)
        result = orchestrator.run_task(
            TaskRequest(
                text=args.text,
                preferred_backend=BackendKind(args.backend),
                auto_approve=args.auto_approve,
            )
        )
        print(json.dumps(result.to_dict(), indent=2))
        return 0

    if args.command == "audit":
        orchestrator = Orchestrator(config, logger)
        print(json.dumps({"tasks": orchestrator.list_recent_tasks(args.limit)}, indent=2))
        return 0

    if args.command == "memory":
        orchestrator = Orchestrator(config, logger)
        if args.list:
            print(json.dumps({"memory": orchestrator.list_memory(args.limit)}, indent=2))
            return 0
        if args.note is not None:
            print(json.dumps({"memory": orchestrator.create_memory_note(args.note)}, indent=2))
            return 0
        if args.delete_id is not None:
            print(
                json.dumps(
                    {
                        "deleted": orchestrator.delete_memory(args.delete_id),
                        "memory_id": args.delete_id,
                    },
                    indent=2,
                )
            )
            return 0
        if args.clear:
            print(json.dumps({"deleted_count": orchestrator.clear_memory()}, indent=2))
            return 0

    if args.command == "approve":
        orchestrator = Orchestrator(config, logger)
        result = orchestrator.approve_task(args.task_id, latest=args.latest)
        print(json.dumps(result.to_dict(), indent=2))
        return 0

    if args.command == "browser":
        controller = BrowserController(config, logger)
        if args.state:
            result = controller.show_state()
        else:
            request_text = (
                f"open browser and show me the page {args.url or ''}".strip()
                if args.show
                else f"open browser {args.url or ''}".strip()
            )
            result = controller.execute_request(request_text, Path.cwd())
        print(
            json.dumps(
                {
                    "executor": result.executor,
                    "command": result.command,
                    "exit_code": result.exit_code,
                    "stdout_text": result.stdout_text,
                    "stderr_text": result.stderr_text,
                },
                indent=2,
            )
        )
        return 0

    if args.command == "screen":
        controller = ScreenCaptureController(config, logger)
        if args.state:
            result = controller.show_state()
        elif args.record:
            seconds = args.seconds or config.screen.default_clip_seconds
            result = controller.record_clip(Path.cwd(), seconds)
        else:
            result = controller.capture_screenshot(Path.cwd())
        print(
            json.dumps(
                {
                    "executor": result.executor,
                    "command": result.command,
                    "exit_code": result.exit_code,
                    "stdout_text": result.stdout_text,
                    "stderr_text": result.stderr_text,
                },
                indent=2,
            )
        )
        return 0

    if args.command == "remote-token":
        server = RemoteApiServer(config, logger)
        token = server.ensure_auth_token()
        bind_host, bind_port = server.server_address
        print(
            json.dumps(
                {
                    "bind_host": bind_host,
                    "port": bind_port,
                    "auth_token": token,
                    "auth_token_path": str(server.token_path),
                },
                indent=2,
            )
        )
        return 0

    return _send(config, args.command)


if __name__ == "__main__":
    raise SystemExit(main())
