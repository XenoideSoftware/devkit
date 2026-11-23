"""The devkit "tools environment".

Installed once per consumer into ``.xenoide/tools/`` by ``mise run setup``:

    conan install .devkit/conan/tools -of .xenoide/tools

It pins the analysis tools that are delivered through Conan (cppcheck and the
in-house cmake-checker). The tasks resolve them from the generated
conanbuild environment file.
"""

from conan import ConanFile


class XenoideTools(ConanFile):
    name = "xenoide-tools"
    version = "0.1.0"
    description = "Pinned analysis tooling for every Xenoide repository"
    license = "MIT"
    package_type = "application"
    settings = "os", "arch", "compiler", "build_type"

    options = {"with_cmake_checker": [True, False]}
    default_options = {"with_cmake_checker": True}

    def requirements(self):
        self.tool_requires("cppcheck/2.21.1")
        if self.options.with_cmake_checker:
            self.tool_requires("cmake-checker/0.1.0")
