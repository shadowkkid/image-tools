from backend.builder.dockerfile_generator import DockerfileGenerator


class TestDockerfileGenerator:
    def setup_method(self):
        self.gen = DockerfileGenerator()

    def test_generate_basic(self):
        result = self.gen.generate(
            base_image="ubuntu:22.04",
            deps_image="registry.example.com/deps:latest",
        )
        assert "FROM registry.example.com/deps:latest AS openhands-deps" in result
        assert "FROM ubuntu:22.04" in result
        assert "COPY --from=openhands-deps /openhands/micromamba" in result
        assert "COPY --from=openhands-deps /openhands/poetry" in result
        assert "COPY --from=openhands-deps /openhands/bin" in result

    def test_generate_with_extra_deps(self):
        result = self.gen.generate(
            base_image="debian:bookworm",
            deps_image="registry.example.com/deps:v1",
            extra_deps="pip install numpy",
        )
        assert "RUN pip install numpy" in result

    def test_generate_ubuntu_skips_system_deps(self):
        result = self.gen.generate(
            base_image="ubuntu:22.04",
            deps_image="registry.example.com/deps:latest",
        )
        # Ubuntu images should NOT get the non-ubuntu system deps block
        assert "libgl1-mesa-glx" not in result

    def test_generate_non_ubuntu_has_system_deps(self):
        result = self.gen.generate(
            base_image="debian:bookworm",
            deps_image="registry.example.com/deps:latest",
        )
        # Non-ubuntu images should get system deps
        assert "apt-get update" in result
        # libgl1-mesa-glx with fallback to libgl1
        assert "libgl1-mesa-glx" in result
        assert "libgl1" in result

    def test_generate_non_ubuntu_libgl_fallback(self):
        """libgl1-mesa-glx should fall back to libgl1 for Debian 13+ compatibility."""
        result = self.gen.generate(
            base_image="swerebenchv2/aio-libs-aiohttp:7869-3a21134",
            deps_image="registry.example.com/deps:latest",
        )
        assert "apt-get install -y --no-install-recommends libgl1-mesa-glx" in result
        assert "apt-get install -y --no-install-recommends libgl1 " in result

    def test_generate_mswebench_skips_system_deps(self):
        result = self.gen.generate(
            base_image="mswebench/some-image:latest",
            deps_image="registry.example.com/deps:latest",
        )
        assert "libgl1-mesa-glx" not in result
