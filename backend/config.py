import os

# Agent configurations
# Each agent defines how images are built. Agents with has_versions=True
# require a version selection; others use top-level deps_image/source_dir.
AGENTS: dict = {
    "OpenHands": {
        "has_versions": True,
        "versions": {
            "0.54.0": {
                "deps_image": os.environ.get(
                    "IMAGE_TOOLS_DEPS_IMAGE",
                    "registry.cn-sh-01.sensecore.cn/ccr-swe-bench-verified/swe-bench/sweb.eval.x86_64.django_1776_django-16100:latest",
                ),
                "source_dir": os.environ.get(
                    "IMAGE_TOOLS_SOURCE_DIR",
                    "/home/SENSETIME/lizimu/workspace/python/OpenHands_Ss",
                ),
            },
        },
    },
}


def get_agent_config(agent: str, agent_version: str = "") -> dict:
    """Resolve agent config to get deps_image and source_dir.

    Raises ValueError if agent or version is invalid.
    """
    agent_def = AGENTS.get(agent)
    if not agent_def:
        raise ValueError(f"Unknown agent: {agent}")

    if agent_def["has_versions"]:
        if not agent_version:
            raise ValueError(f"Agent '{agent}' requires a version")
        version_cfg = agent_def["versions"].get(agent_version)
        if not version_cfg:
            raise ValueError(f"Unknown version '{agent_version}' for agent '{agent}'")
        return version_cfg
    else:
        return {"deps_image": agent_def["deps_image"], "source_dir": agent_def["source_dir"]}
