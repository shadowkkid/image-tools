import os

from jinja2 import Environment, FileSystemLoader

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")


class DockerfileGenerator:
    def __init__(self, template_dir: str | None = None):
        self.env = Environment(
            loader=FileSystemLoader(template_dir or TEMPLATE_DIR)
        )

    def generate(
        self,
        base_image: str,
        deps_image: str,
        extra_deps: str | None = None,
    ) -> str:
        """Render Dockerfile.j2 template with given parameters."""
        template = self.env.get_template("Dockerfile.j2")
        return template.render(
            base_image=base_image,
            deps_image=deps_image,
            extra_deps=extra_deps or "",
        )
