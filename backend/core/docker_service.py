import asyncio
import json
import os
import logging

logger = logging.getLogger(__name__)


def _parse_registry_host(registry_with_prefix: str) -> str:
    """Extract registry host from a registry address that may contain a prefix path.

    e.g. 'registry.sensecore.tech/ccr-sandbox-swe' -> 'registry.sensecore.tech'
    """
    parts = registry_with_prefix.strip().split("/")
    # The first part with a dot is likely the registry host
    if "." in parts[0] or ":" in parts[0]:
        return parts[0]
    return registry_with_prefix


class DockerService:

    @staticmethod
    def check_registry_auth(registry_with_prefix: str) -> tuple[bool, str]:
        """Check if docker is logged in to the given registry by reading ~/.docker/config.json."""
        registry_host = _parse_registry_host(registry_with_prefix)
        config_path = os.path.expanduser("~/.docker/config.json")

        if not os.path.exists(config_path):
            return False, f"Docker config not found at {config_path}"

        try:
            with open(config_path) as f:
                config = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            return False, f"Failed to read docker config: {e}"

        auths = config.get("auths", {})
        # Check if registry host exists in auths
        for key in auths:
            # Match exact or with https:// prefix
            if registry_host in key:
                return True, f"Already logged in to {registry_host}"

        return False, f"Not logged in to {registry_host}"

    @staticmethod
    async def login(registry: str, username: str, password: str) -> tuple[bool, str]:
        """Execute docker login with provided credentials."""
        registry_host = _parse_registry_host(registry)
        proc = await asyncio.create_subprocess_exec(
            "docker", "login", "-u", username, "--password-stdin", registry_host,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(input=password.encode())
        output = (stdout.decode() + stderr.decode()).strip()

        if proc.returncode == 0:
            return True, output or "Login Succeeded"
        return False, output or "Login failed"

    @staticmethod
    async def build(
        build_context_path: str,
        tags: list[str],
        build_args: list[str] | None = None,
    ) -> tuple[bool, str, list[str]]:
        """Execute docker buildx build. Returns (success, output_log, output_lines)."""
        cmd = [
            "docker", "buildx", "build",
            "--progress=plain",
            "--load",
            "--provenance=false",
        ]
        for tag in tags:
            cmd.extend(["-t", tag])

        if build_args:
            cmd.extend(build_args)

        cmd.append(build_context_path)

        logger.info(f"Running: {' '.join(cmd)}")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        output_lines = []
        assert proc.stdout is not None
        async for line in proc.stdout:
            decoded = line.decode().rstrip()
            if decoded:
                output_lines.append(decoded)
                logger.debug(decoded)

        await proc.wait()

        output = "\n".join(output_lines)
        if proc.returncode == 0:
            return True, output, output_lines
        return False, output, output_lines

    @staticmethod
    async def tag(source_image: str, target_image: str) -> tuple[bool, str]:
        """Execute docker tag."""
        proc = await asyncio.create_subprocess_exec(
            "docker", "tag", source_image, target_image,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        output = (stdout.decode() + stderr.decode()).strip()

        if proc.returncode == 0:
            return True, output or "Tagged successfully"
        return False, output or "Tag failed"

    @staticmethod
    async def push(image: str) -> tuple[bool, str]:
        """Execute docker push."""
        proc = await asyncio.create_subprocess_exec(
            "docker", "push", image,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        output_lines = []
        assert proc.stdout is not None
        async for line in proc.stdout:
            decoded = line.decode().rstrip()
            if decoded:
                output_lines.append(decoded)

        await proc.wait()

        output = "\n".join(output_lines)
        if proc.returncode == 0:
            return True, output or "Push succeeded"
        return False, output or "Push failed"
