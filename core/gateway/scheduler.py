"""Gateway manager: lifecycle management for multiple gateways."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from core.gateway.base import (
    GatewayBase,
    GatewayConfig,
    GatewayHealth,
    GatewayStatus,
    PlatformType,
)
from core.gateway.router import MessageRouter

logger = logging.getLogger(__name__)


@dataclass
class GatewayInstance:
    """A managed gateway instance."""
    config: GatewayConfig
    gateway: GatewayBase | None = None
    health: GatewayHealth = field(default_factory=GatewayHealth)
    started_at: float = 0.0
    task: asyncio.Task | None = None


@dataclass
class GatewayManagerStatus:
    """Aggregate status for all managed gateways."""
    running: bool = False
    total_gateways: int = 0
    running_gateways: int = 0
    error_gateways: int = 0
    gateway_statuses: dict[str, dict[str, Any]] = field(default_factory=dict)
    total_sessions: int = 0
    uptime_seconds: float = 0.0


class GatewayManager:
    """Manages the lifecycle of multiple gateway instances.

    Responsibilities:
    - Create and configure gateway instances from config
    - Start/stop/restart gateways
    - Health monitoring and auto-reconnect
    - Status reporting
    - Integration with MessageRouter for message routing
    """

    def __init__(self) -> None:
        self._instances: dict[str, GatewayInstance] = {}
        self._router = MessageRouter()
        self._running = False
        self._health_tasks: dict[str, asyncio.Task] = {}
        self._health_check_interval: float = 30.0
        self._start_time: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def router(self) -> MessageRouter:
        return self._router

    @property
    def running(self) -> bool:
        return self._running

    # -------------------------------------------------------------------------
    # Configuration
    # -------------------------------------------------------------------------

    def add_gateway(self, config: GatewayConfig) -> GatewayInstance:
        """Add a gateway configuration. Gateway is not started until start() is called."""
        key = config.platform.value
        instance = GatewayInstance(
            config=config,
            health=GatewayHealth(status=GatewayStatus.STOPPED, config_valid=True),
        )
        self._instances[key] = instance
        logger.info("Added gateway config: %s", key)
        return instance

    def remove_gateway(self, platform: PlatformType | str) -> None:
        """Remove a gateway configuration."""
        key = platform.value if isinstance(platform, PlatformType) else platform
        self._instances.pop(key, None)
        logger.info("Removed gateway config: %s", key)

    def get_gateway_config(self, platform: PlatformType | str) -> GatewayConfig | None:
        """Get config for a gateway."""
        key = platform.value if isinstance(platform, PlatformType) else platform
        inst = self._instances.get(key)
        return inst.config if inst else None

    def list_gateways(self) -> list[GatewayInstance]:
        """List all configured gateway instances."""
        return list(self._instances.values())

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    async def start(self) -> None:
        """Start all configured gateways."""
        if self._running:
            return
        self._running = True
        self._start_time = time.time()
        logger.info("GatewayManager: starting %d gateway(s)", len(self._instances))

        for key, instance in self._instances.items():
            if not instance.config.enabled:
                logger.info("Skipping disabled gateway: %s", key)
                continue
            await self._start_gateway(instance, key)

        # Start health monitoring
        self._health_tasks["manager"] = asyncio.create_task(
            self._health_monitor_loop(),
            name="gateway-health-monitor",
        )
        logger.info("GatewayManager started")

    async def stop(self) -> None:
        """Stop all gateways."""
        self._running = False
        logger.info("GatewayManager: stopping...")

        # Cancel health monitoring
        if "manager" in self._health_tasks:
            self._health_tasks["manager"].cancel()
            self._health_tasks.pop("manager", None)

        for key in list(self._instances.keys()):
            await self._stop_gateway(key)

        # Stop router
        await self._router.stop()

        logger.info("GatewayManager stopped")

    async def restart(self) -> None:
        """Restart all gateways."""
        await self.stop()
        await self.start()

    async def start_gateway(self, platform: PlatformType | str) -> bool:
        """Start a single gateway by platform name."""
        key = platform.value if isinstance(platform, PlatformType) else platform
        instance = self._instances.get(key)
        if not instance:
            logger.warning("Gateway not configured: %s", key)
            return False
        if instance.config and not instance.config.enabled:
            logger.warning("Gateway disabled: %s", key)
            return False
        return await self._start_gateway(instance, key)

    async def stop_gateway(self, platform: PlatformType | str) -> bool:
        """Stop a single gateway by platform name."""
        key = platform.value if isinstance(platform, PlatformType) else platform
        return await self._stop_gateway(key)

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    async def _create_gateway(self, instance: GatewayInstance) -> GatewayBase | None:
        """Create a gateway instance from config. Returns None if creation fails."""
        from core.gateway.telegram import TelegramGateway
        from core.gateway.discord import DiscordGateway
        from core.gateway.slack import SlackGateway
        from core.gateway.whatsapp import WhatsAppGateway
        from core.gateway.signal import SignalGateway
        from core.gateway.matrix import MatrixGateway
        from core.gateway.webhook import WebhookGateway
        from core.gateway.feishu import FeishuGateway
        from core.gateway.wechat import WechatGateway
        from core.gateway.homeassistant import HomeAssistantGateway

        config = instance.config
        gateway: GatewayBase | None = None

        try:
            if config.platform == PlatformType.TELEGRAM:
                gateway = TelegramGateway(config)
            elif config.platform == PlatformType.DISCORD:
                gateway = DiscordGateway(config)
            elif config.platform == PlatformType.SLACK:
                gateway = SlackGateway(config)
            elif config.platform == PlatformType.WHATSAPP:
                gateway = WhatsAppGateway(config)
            elif config.platform == PlatformType.SIGNAL:
                gateway = SignalGateway(config)
            elif config.platform == PlatformType.MATRIX:
                gateway = MatrixGateway(config)
            elif config.platform == PlatformType.WEBHOOK:
                gateway = WebhookGateway(config)
            elif config.platform == PlatformType.FEISHU:
                gateway = FeishuGateway(config)
            elif config.platform == PlatformType.WECHAT:
                gateway = WechatGateway(config)
            elif config.platform == PlatformType.HOMEASSISTANT:
                gateway = HomeAssistantGateway(config)
            else:
                logger.warning("Unknown platform: %s", config.platform)
        except Exception as e:
            logger.error("Failed to create gateway %s: %s", config.platform.value, e)
            instance.health.config_valid = False
            instance.health.status = GatewayStatus.ERROR
            instance.health.last_error = str(e)
            return None

        if gateway:
            self._router.register_gateway(gateway)
            self._router.set_response_callback(
                config.platform,
                lambda uid, cid, txt, files: asyncio.ensure_future(
                    gateway.send_message(uid, cid, txt or "", files or [])
                ),
            )

        return gateway

    async def _start_gateway(self, instance: GatewayInstance, key: str) -> bool:
        """Start a single gateway instance."""
        try:
            instance.health.status = GatewayStatus.STARTING
            instance.health.config_valid = True
            gateway = instance.gateway or await self._create_gateway(instance)

            if not gateway:
                instance.health.status = GatewayStatus.ERROR
                return False

            success = await gateway.start()
            if success:
                instance.gateway = gateway
                instance.health.status = GatewayStatus.RUNNING
                instance.started_at = time.time()
                self._router.register_gateway(gateway)

                # Start reconnect loop if needed
                if gateway.config.auto_reconnect:
                    instance.task = asyncio.create_task(
                        gateway._reconnect_loop(),
                        name=f"reconnect-{key}",
                    )
            else:
                instance.health.status = GatewayStatus.ERROR
                instance.health.last_error = "Gateway start() returned False"

            return success

        except Exception as e:
            instance.health.status = GatewayStatus.ERROR
            instance.health.last_error = str(e)
            logger.error("Failed to start gateway %s: %s", key, e)
            return False

    async def _stop_gateway(self, key: str) -> bool:
        """Stop a single gateway instance."""
        instance = self._instances.get(key)
        if not instance or not instance.gateway:
            return False

        gateway = instance.gateway
        gateway._running = False

        # Cancel reconnect task
        if instance.task:
            instance.task.cancel()
            try:
                await instance.task
            except asyncio.CancelledError:
                pass
            instance.task = None

        await gateway.stop()
        instance.health.status = GatewayStatus.STOPPED
        self._router.unregister_gateway(gateway.config.platform)
        logger.info("Stopped gateway: %s", key)
        return True

    async def _health_monitor_loop(self) -> None:
        """Periodic health check for all gateways."""
        while self._running:
            try:
                for key, instance in self._instances.items():
                    if not instance.gateway:
                        continue
                    try:
                        health = instance.gateway.health_status()
                        instance.health = health
                        if health.status == GatewayStatus.ERROR:
                            logger.warning(
                                "Gateway %s in error state: %s",
                                key, health.last_error,
                            )
                    except Exception as e:
                        logger.error("Health check failed for %s: %s", key, e)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Health monitor error: %s", e)

            await asyncio.sleep(self._health_check_interval)

    # -------------------------------------------------------------------------
    # Status
    # -------------------------------------------------------------------------

    def get_status(self) -> GatewayManagerStatus:
        """Get aggregate status report."""
        running_count = 0
        error_count = 0
        statuses: dict[str, dict[str, Any]] = {}

        for key, instance in self._instances.items():
            if not instance.config:
                continue
            status_entry: dict[str, Any] = {
                "enabled": instance.config.enabled,
                "config_valid": instance.health.config_valid,
                "uptime_seconds": 0.0,
            }
            if instance.gateway:
                health = instance.gateway.health_status()
                status_entry["status"] = health.status.value
                status_entry["messages_processed"] = health.messages_processed
                status_entry["errors"] = health.errors
                if instance.started_at:
                    status_entry["uptime_seconds"] = time.time() - instance.started_at
                if health.status == GatewayStatus.RUNNING:
                    running_count += 1
                elif health.status == GatewayStatus.ERROR:
                    error_count += 1
            else:
                status_entry["status"] = "not_started"

            statuses[key] = status_entry

        uptime = (time.time() - self._start_time) if self._start_time else 0.0

        return GatewayManagerStatus(
            running=self._running,
            total_gateways=len(self._instances),
            running_gateways=running_count,
            error_gateways=error_count,
            gateway_statuses=statuses,
            uptime_seconds=uptime,
        )

    def get_gateway_status(
        self, platform: PlatformType | str,
    ) -> dict[str, Any] | None:
        """Get status for a specific gateway."""
        key = platform.value if isinstance(platform, PlatformType) else platform
        instance = self._instances.get(key)
        if not instance:
            return None
        report = {
            "enabled": instance.config.enabled if instance.config else False,
            "config_valid": instance.health.config_valid,
            "status": instance.health.status.value,
            "messages_processed": instance.health.messages_processed,
            "errors": instance.health.errors,
            "last_error": instance.health.last_error,
            "reconnect_attempts": instance.health.reconnect_attempts,
        }
        if instance.gateway:
            status = instance.gateway.health_status()
            report.update({
                "status": status.status.value,
                "messages_processed": status.messages_processed,
                "errors": status.errors,
                "last_error": status.last_error,
            })
            report["uptime_seconds"] = (
                time.time() - instance.started_at
                if instance.started_at else 0.0
            )
        return report
