"""Conan hooks shipped with the devkit.

The hook is intentionally conservative. It only fails when a recipe still uses
the retired ``@xenoide/xenoide`` user/channel, which is the one rule whose
silent violation would pull a second copy of every in-house package.
"""

from conan.errors import ConanException


def pre_export(conanfile):
    if getattr(conanfile, "channel", None) == "xenoide" or \
            getattr(conanfile, "user", None) == "xenoide":
        reference = getattr(conanfile, "ref", None) or conanfile.display_name
        raise ConanException(
            f"{reference} still uses the retired '@xenoide/xenoide' channel. "
            "In-house packages are consumed as bare 'name/version'."
        )
