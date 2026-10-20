"""Record that the character requires the standalone animation repair package.

The skill produces character content only. The animation repair is a separate
FBMOD and must be enabled in the mod manager together with the character; it is
never built, merged or copied by this pipeline.
"""

PACKAGE_NAME = "dsr_animation_fix.fbmod"
NOTE = ("Load the standalone dsr_animation_fix.fbmod together with this character "
        "package. The repair is not merged into character builds.")


def requirement(config):
    enabled = bool(config.get("animation_fix"))
    return {"enabled": enabled, "required": enabled, "separate_package": enabled,
            "merged": False, "package_name": PACKAGE_NAME if enabled else None,
            "note": NOTE if enabled else None}


def verify(report):
    if report.get("merged") is not False:
        raise ValueError("Animation repair must remain a separate package.")
    if report.get("enabled") and report.get("package_name") != PACKAGE_NAME:
        raise ValueError("Animation repair reminder is missing the standalone package name.")
    return {"enabled": bool(report.get("enabled")), "required": bool(report.get("required")),
            "separate_package": bool(report.get("separate_package")), "merged": False,
            "package_name": PACKAGE_NAME, "note": NOTE}
