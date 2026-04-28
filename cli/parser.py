"""NoMan CLI argument parser."""

from __future__ import annotations

import argparse
import sys

_COMMANDS = {
    "doctor", "review", "rollback", "memory", "skill", "stats", "emergency",
    "init", "catalog", "gateway", "cron", "webhook",
    "voice", "vision", "image",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="noman",
        description="NoMan -- a model-agnostic agentic coding CLI",
        add_help=False,
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="Override the default model provider",
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help="Show reasoning before executing",
    )
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="Disable all write operations",
    )
    parser.add_argument(
        "--help", "-h",
        action="help",
        help="Show this help message and exit",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--max-calls",
        type=int,
        default=10,
        help="Max tool calls per turn (default: 10)",
    )
    return parser


def build_subparsers() -> argparse.ArgumentParser:
    parser = build_parser()
    sub = parser.add_subparsers(dest="command")

    # -- doctor --
    sub.add_parser("doctor", help="Run health checks on providers, config, memory, disk")

    # -- review --
    rev = sub.add_parser("review", help="Show diff of recent changes")
    rev.add_argument("file", nargs="?", default=None, help="Optional file to diff")
    rev.add_argument("--n", type=int, default=5, help="Number of recent commits to show (default: 5)")

    # -- rollback --
    rollback = sub.add_parser("rollback", help="Revert agent self-modifications")
    rollback.add_argument("--n", type=int, default=1, help="Number of changes to revert")
    rollback.add_argument("--to", dest="trace_id", help="Revert to specific trace ID")
    rollback.add_argument("-l", "--list", dest="list_rollbacks", action="store_true",
                          help="List available rollbacks instead of reverting")

    # -- memory --
    mem = sub.add_parser("memory", help="Memory operations")
    mem.add_argument("subcmd", choices=["list", "get", "set", "delete"],
                     help="Memory subcommand")
    mem.add_argument("tier", nargs="?", default=None, help="Memory tier: episodic|semantic|procedural")
    mem.add_argument("scope", nargs="?", default=None, help="Memory scope: project|global")
    mem.add_argument("key", nargs="?", default=None, help="Memory key")
    mem.add_argument("value", nargs="?", default=None, help="Memory value (for set)")
    mem.add_argument("--tier", dest="tier_filter", default=None,
                     help="Filter by tier (for list)")
    mem.add_argument("--scope", dest="scope_filter", default=None,
                     help="Filter by scope (for list)")

    # -- skill --
    skill = sub.add_parser("skill", help="Skill operations")
    skill.add_argument("subcmd", choices=["list", "get", "set", "add", "review", "approve", "discard", "patterns", "stats"],
                       help="Skill subcommand")
    skill.add_argument("name", nargs="?", default=None, help="Skill name")
    skill.add_argument("content", nargs="?", default=None, help="Skill content (for set/add)")
    skill.add_argument("file", nargs="?", default=None, help="Source file (for add)")
    skill.add_argument("draft_id", nargs="?", default=None, help="Draft ID (for approve/discard)")
    skill.add_argument("--min-occurrences", "-m", type=int, default=3, help="Min occurrences for pattern detection (for 'patterns')")

    # -- stats --
    sub.add_parser("stats", help="Show execution stats")

    # -- emergency --
    emerg = sub.add_parser("emergency", help="Emergency controls")
    emerg.add_argument("action", choices=["stop", "disable-self-improve", "read-only", "lockdown"],
                       help="Emergency action")

    # -- init --
    sub.add_parser("init", help="Scaffold .noman/ directory")

    # -- catalog --
    cat = sub.add_parser("catalog", help="List all Hermes agent tools and features")
    cat.add_argument("--tools", "-t", action="store_true", help="Show tools only")
    cat.add_argument("--skills", "-s", action="store_true", help="Show skills only")
    cat.add_argument("--summary", action="store_true", help="Show summary counts only")
    cat.add_argument("--by-category", "-c", action="store_true", help="Group by category")

    # -- gateway --
    gw = sub.add_parser("gateway", help="Manage multi-platform gateways")
    gw_sub = gw.add_subparsers(dest="gateway_subcmd")

    gw_run = gw_sub.add_parser("run", help="Start configured gateways")
    gw_run.add_argument("--platforms", nargs="*", default=[],
                        help="Platforms to start (default: all enabled)")
    gw_run.add_argument("--daemon", "-d", action="store_true",
                        help="Run as daemon in background")

    gw_status = gw_sub.add_parser("status", help="Show gateway status")
    gw_status.add_argument("--platform", default=None,
                           help="Show status for specific platform")
    gw_status.add_argument("--json", action="store_true",
                           help="Output as JSON")

    gw_setup = gw_sub.add_parser("setup", help="Configure gateway platforms")
    gw_setup.add_argument("platform", nargs="?", default=None,
                          help="Platform to configure (telegram, discord, slack, etc.)")
    gw_setup.add_argument("--token", default=None, help="Bot token")
    gw_setup.add_argument("--port", type=int, default=None, help="Webhook port")

    gw_install = gw_sub.add_parser("install", help="Install gateway as a service")
    gw_install.add_argument("--systemd", action="store_true",
                            help="Install as systemd service")
    gw_install.add_argument("--launchd", action="store_true",
                            help="Install as launchd service (macOS)")

    gw_start = gw_sub.add_parser("start", help="Start gateways")
    gw_start.add_argument("--platform", default=None, help="Specific platform to start")

    gw_stop = gw_sub.add_parser("stop", help="Stop gateways")
    gw_stop.add_argument("--platform", default=None, help="Specific platform to stop")

    gw_restart = gw_sub.add_parser("restart", help="Restart gateways")
    gw_restart.add_argument("--platform", default=None, help="Specific platform to restart")

    gw_list = gw_sub.add_parser("list", help="List all gateway configurations")

    # -- cron --
    cron = sub.add_parser("cron", help="Manage scheduled cron jobs")
    cron_sub = cron.add_subparsers(dest="cron_subcmd")

    cron_list = cron_sub.add_parser("list", help="List all cron jobs")
    cron_list.add_argument("--status", default=None, help="Filter by status (pending/running/completed/failed/paused)")
    cron_list.add_argument("--enabled", action="store_true", help="Only show enabled jobs")
    cron_list.add_argument("--json", action="store_true", help="Output as JSON")

    cron_create = cron_sub.add_parser("create", help="Create a new cron job")
    cron_create.add_argument("schedule", help="Cron expression or interval (e.g. '0 9 * * *' or '30m')")
    cron_create.add_argument("prompt", help="Task description for the orchestrator")
    cron_create.add_argument("--name", default=None, help="Job name (auto-generated if omitted)")
    cron_create.add_argument("--delivery", default="origin", help="Delivery target: origin, local, or gateway:chat_id")
    cron_create.add_argument("--skills", default=None, help="Comma-separated skill names to load")
    cron_create.add_argument("--repeat", type=int, default=None, help="Number of repeats (None = forever)")
    cron_create.add_argument("--max-attempts", type=int, default=0, help="Max retry attempts on failure")

    cron_edit = cron_sub.add_parser("edit", help="Edit a cron job")
    cron_edit.add_argument("job_id", help="Job UUID to edit")
    cron_edit.add_argument("--name", default=None, help="New job name")
    cron_edit.add_argument("--schedule", default=None, help="New schedule")
    cron_edit.add_argument("--prompt", default=None, help="New prompt")
    cron_edit.add_argument("--delivery", default=None, help="New delivery target")
    cron_edit.add_argument("--skills", default=None, help="Comma-separated skill names")
    cron_edit.add_argument("--repeat", type=int, default=None, help="New repeat count")
    cron_edit.add_argument("--enable", action="store_true", help="Enable the job")
    cron_edit.add_argument("--disable", action="store_true", help="Disable the job")

    cron_pause = cron_sub.add_parser("pause", help="Pause a cron job")
    cron_pause.add_argument("job_id", help="Job UUID to pause")

    cron_resume = cron_sub.add_parser("resume", help="Resume a paused cron job")
    cron_resume.add_argument("job_id", help="Job UUID to resume")

    cron_remove = cron_sub.add_parser("remove", help="Remove a cron job")
    cron_remove.add_argument("job_id", help="Job UUID to remove")

    cron_run = cron_sub.add_parser("run", help="Run a job immediately")
    cron_run.add_argument("job_id", help="Job UUID to run")

    cron_status = cron_sub.add_parser("status", help="Show scheduler status")

    # -- webhook --
    wh = sub.add_parser("webhook", help="Manage webhook subscriptions")
    wh_sub = wh.add_subparsers(dest="webhook_subcmd")

    wh_list = wh_sub.add_parser("list", help="List all webhook subscriptions")
    wh_list.add_argument("--json", action="store_true", help="Output as JSON")

    wh_subscribe = wh_sub.add_parser("subscribe", help="Create a webhook subscription")
    wh_subscribe.add_argument("name", help="Subscription name")
    wh_subscribe.add_argument("--path", default="/webhooks/default", help="URL path (default: /webhooks/default)")
    wh_subscribe.add_argument("--events", default=None, help="Comma-separated event types")
    wh_subscribe.add_argument("--delivery", default="origin", help="Delivery target")
    wh_subscribe.add_argument("--headers", default=None, help="Comma-separated key=value headers to validate")

    wh_remove = wh_sub.add_parser("remove", help="Remove a webhook subscription")
    wh_remove.add_argument("name", help="Subscription name to remove")

    wh_test = wh_sub.add_parser("test", help="Test a webhook subscription")
    wh_test.add_argument("name", help="Subscription name to test")

    # --- Voice subcommand ---
    voice = sub.add_parser("voice", help="Voice (STT/TTS) operations")
    voice_sub = voice.add_subparsers(dest="voice_subcmd")

    voice_stt = voice_sub.add_parser("stt", help="Transcribe audio to text")
    voice_stt.add_argument("--file", "-f", dest="audio_file", default=None, help="Audio file path")
    voice_stt.add_argument("--text", dest="text_input", default=None, help="Text input for TTS (alternative to --file)")
    voice_stt.add_argument("--provider", default=None, help="STT provider override")
    voice_stt.add_argument("--language", default=None, help="Language code (e.g., en, es, fr)")

    voice_tts = voice_sub.add_parser("tts", help="Text-to-speech synthesis")
    voice_tts.add_argument("--text", "-t", required=True, help="Text to synthesize")
    voice_tts.add_argument("--output", "-o", default=None, help="Output file path")
    voice_tts.add_argument("--provider", default=None, help="TTS provider override")
    voice_tts.add_argument("--speed", type=float, default=1.0, help="Speech speed (0.5-2.0)")
    voice_tts.add_argument("--pitch", type=int, default=0, help="Pitch shift in semitones")

    voice_list = voice_sub.add_parser("list", help="List available voice providers")

    # --- Vision subcommand ---
    vision = sub.add_parser("vision", help="Image analysis (vision) operations")
    vision.add_argument("--image", "-i", required=True, help="Image file path or URL")
    vision.add_argument("--prompt", "-p", default=None, help="Analysis prompt/question")
    vision.add_argument("--task", "-t", default="describe",
                        choices=["describe", "ocr", "object_detection", "analysis", "question_answer"],
                        help="Vision task type")
    vision.add_argument("--provider", default=None, help="Vision provider override")

    # --- Image generation subcommand ---
    image = sub.add_parser("image", help="Image generation operations")
    image_sub = image.add_subparsers(dest="image_subcmd")

    image_gen = image_sub.add_parser("generate", help="Generate an image from text")
    image_gen.add_argument("--prompt", "-p", required=True, help="Image generation prompt")
    image_gen.add_argument("--aspect", "-a", default="square",
                           choices=["landscape", "square", "portrait"],
                           help="Aspect ratio (landscape, square, portrait)")
    image_gen.add_argument("--provider", default=None, help="Image generation provider override")
    image_gen.add_argument("--model", default=None, help="Model override")
    image_gen.add_argument("--negative-prompt", "-n", default=None, help="Negative prompt")
    image_gen.add_argument("--count", "-c", type=int, default=1, help="Number of images to generate")
    image_gen.add_argument("--output", "-o", default=None, help="Output directory")

    image_gen_list = image_sub.add_parser("list", help="List available image generation providers")

    return parser


def parse_args(argv: list[str] | None = None):
    argv = list(argv) if argv is not None else sys.argv[1:]

    # Parse global flags first
    global_parser = build_parser()
    global_ns, remainder = global_parser.parse_known_args(argv)

    # If no remainder -> REPL mode
    if not remainder:
        global_ns.command = None
        global_ns.task = None
        return global_ns

    # If first remainder arg is a known command -> subparser mode
    if remainder[0] in _COMMANDS:
        sub_parser = build_subparsers()
        ns = sub_parser.parse_args(argv)
        ns.task = None
        return ns

    # Otherwise -> task mode (remainder is the task string)
    global_ns.command = None
    global_ns.task = " ".join(remainder)
    return global_ns
