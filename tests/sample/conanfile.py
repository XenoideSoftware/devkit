from conan import ConanFile


class SampleConan(ConanFile):
    name = "xenoide-sample"
    version = "0.1.0"
    python_requires = "xenoide-base/0.1.1"
    python_requires_extend = "xenoide-base.XenoideCMake"
    package_type = "application"

    exports_sources = "CMakeLists.txt", "src/*", "test/*"

    def requirements(self):
        self.requires("fmt/11.0.2")
