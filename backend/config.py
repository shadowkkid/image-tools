import os

# Default deps image (configurable via environment variable)
DEPS_IMAGE = os.environ.get(
    "IMAGE_TOOLS_DEPS_IMAGE",
    "registry.cn-sh-01.sensecore.cn/ccr-swe-bench-verified/swe-bench/sweb.eval.x86_64.django_1776_django-16100:latest",
)
