"""
Single source of truth for Orekit JVM startup + orekit-data loading
via orekit_jpype.

CRITICAL INVARIANTS (Orekit 11+ / orekit_jpype on PyPI):
  1) orekit_jpype.initVM(vmargs=f"-XX:ErrorFile={Path(tempfile.gettempdir()) / 'leap-jvm-error-%p.log'}") MUST be called before any `from org.*` import.
  2) Data is registered with:
         dpm = DataContext.getDefault().getDataProvidersManager()
         dpm.addProvider(DirectoryCrawler(File("/path/to/orekit-data")))
     The old `addDefaultProvider(String)` method was REMOVED in Orekit 11.
  3) For a .zip / .jar archive, use ZipJarCrawler instead of DirectoryCrawler.

Importing this module initialises everything as a side-effect (idempotent).
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_JVM_STARTED = False
_DATA_LOADED = False

_DEFAULT_DATA_CANDIDATES = [
    os.environ.get("OREKIT_DATA"),
    "orekit-data",
    "./orekit-data",
    "../orekit-data",
    os.path.expanduser("~/orekit-data"),
]


# ---------------------------------------------------------------------------
# JVM startup
# ---------------------------------------------------------------------------
def start_jvm() -> None:
    """Start the orekit_jpype JVM.  Idempotent."""
    global _JVM_STARTED
    if _JVM_STARTED:
        return
    import orekit_jpype
    orekit_jpype.initVM(vmargs=f"-XX:ErrorFile={Path(tempfile.gettempdir()) / 'leap-jvm-error-%p.log'}")
    _JVM_STARTED = True


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_orekit_data(
    path: str | os.PathLike | None = None,
    force: bool = False,
) -> None:
    """
    Attach the orekit-data folder (or .zip / .jar archive) to Orekit's
    DataProvidersManager using the Orekit 11+ API:

        dpm = DataContext.getDefault().getDataProvidersManager()
        dpm.addProvider(DirectoryCrawler(File("/path/to/orekit-data")))

    Notes:
      * `addDefaultProvider(String)` was REMOVED in Orekit 11.0; do NOT use it.
      * If `addDefaultProviders()` is also desired (loads built-in classpath
        defaults), call it explicitly AFTER this function returns. For most
        users with their own orekit-data folder it is unnecessary.
      * A post-load verification step attempts to read EGM2008 (degree 2,
        order 0). If that throws, the folder is missing critical files
        (e.g. egm2008.gfc) and we raise a clear RuntimeError.

    Args:
        path : Path to the orekit-data FOLDER or to a .zip/.jar archive.
               If None, the default candidates list is searched.
        force: If True, re-run even if already loaded.
    """
    global _DATA_LOADED
    if _DATA_LOADED and not force:
        return

    # ---- Resolve the path ------------------------------------------------
    resolved: str | None = None
    if path is None:
        for c in _DEFAULT_DATA_CANDIDATES:
            if c and Path(c).exists():
                resolved = c
                break
    else:
        resolved = str(path)

    if resolved is None:
        raise FileNotFoundError(
            "Orekit data folder not found.  Either:\n"
            "  1) set the OREKIT_DATA env var to your orekit-data path,\n"
            "  2) call load_orekit_data('/path/to...') explicitly, or\n"
            "  3) put the folder at ./orekit-data relative to your CWD.\n"
            f"  Looked for: {_DEFAULT_DATA_CANDIDATES}"
        )

    p = Path(resolved)
    if not p.exists():
        raise FileNotFoundError(f"Orekit-data path does not exist: {resolved}")

    # ---- JVM must be up before any Java import ---------------------------
    start_jvm()

    # Java imports happen HERE, after JVM is up.
    from java.io import File
    from org.orekit.data import (
        DataContext,
        DirectoryCrawler,
        ZipJarCrawler,
    )

    dpm = DataContext.getDefault().getDataProvidersManager()

    # Optionally clear previously registered providers (for force=True).
    if force:
        try:
            dpm.clearProviders()
        except Exception:
            # Some Orekit versions don't expose clearProviders(); ignore.
            pass

    # ---- Build the appropriate crawler -----------------------------------
    if p.is_dir():
        provider = DirectoryCrawler(File(str(p)))
    elif p.is_file() and p.suffix.lower() in (".zip", ".jar"):
        provider = ZipJarCrawler(File(str(p)))
    else:
        raise ValueError(
            "orekit-data path must be a directory or a .zip/.jar archive. "
            f"Got: {resolved}"
        )

    # ---- Register --------------------------------------------------------
    dpm.addProvider(provider)

    # ---- Verification: try to read EGM2008 (degree 2, order 0) ----------
    # If the folder is missing egm2008.gfc or the provider didn't actually
    # register, this throws immediately with a clear message instead of
    # letting propagation fail hours later.
    try:
        from org.orekit.forces.gravity.potential import GravityFieldFactory
        _ = GravityFieldFactory.getNormalizedProvider(2, 0)
    except Exception as e:
        _DATA_LOADED = False
        raise RuntimeError(
            "orekit-data path registered, but EGM2008 verification failed.\n"
            f"  Path: {resolved}\n"
            "  Expected file inside that folder: egm2008.gfc\n"
            "  Check that the folder contents are valid (look for\n"
            "  egm2008.gfc, eopc04/, tpc/, utc-tai.history, etc.).\n"
            f"  Original error: {e}"
        ) from e

    _DATA_LOADED = True


# ---------------------------------------------------------------------------
# Public convenience API
# ---------------------------------------------------------------------------
def ensure_initialized(
    data_path: str | os.PathLike | None = None,
) -> None:
    """Start JVM (idempotent) then load orekit-data (idempotent)."""
    start_jvm()
    load_orekit_data(data_path)


def is_initialized() -> bool:
    return _JVM_STARTED and _DATA_LOADED


# ---------------------------------------------------------------------------
# Auto-initialise on first import.
# This is what makes `import engine.orekit_runtime` sufficient to make every
# subsequent `from org.*` import work anywhere else in the codebase.
# ---------------------------------------------------------------------------
ensure_initialized()
