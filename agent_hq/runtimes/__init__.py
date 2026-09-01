"""Runtime adapters. Two verification tiers, disclosed per-adapter and
surfaced by `agent-hq doctor` -- see models.RUNTIME_VERIFICATION.

VERIFIED means: checked against the real installed CLI's --help output,
and proven against at least one real invocation during development.

DOCUMENTED means: built from the tool's official documentation, but this
tool wasn't installed in the environment this was developed in, so
nothing here has been run for real. The code is honest about that in its
own docstring, not just in a README table somewhere else.
"""
