"""
Standalone child script for fetching Spotify track metadata via spotDL.

Executed as a subprocess by SpotDLManager.fetch_tracks(). Communicates
results back to the parent process via a line-based protocol on stdout:

    __TRACK__{json}   – one fetched track
    __WARN__{json}    – a warning message
    __DONE__{json}    – completion summary
    __ERR__{json}     – fatal error
"""
from __future__ import annotations

import json
import logging
import sys


def _emit(obj: str) -> None:
    try:
        sys.stdout.write(obj)
        sys.stdout.flush()
    except Exception:
        pass


def _safe_json(obj: object) -> str:
    try:
        return json.dumps(obj, ensure_ascii=True)
    except (TypeError, ValueError):
        return json.dumps(str(obj), ensure_ascii=True)


class _ProtocolHandler(logging.Handler):
    """Forward WARNING+ log records as __WARN__ protocol lines."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if record.levelno < logging.WARNING:
                return
            msg = record.getMessage()
        except Exception:
            msg = getattr(record, "msg", "?")
        _emit("__WARN__" + _safe_json(str(msg)[:300]) + "\n")


def _restore_child_stdio() -> None:
    """Best-effort: force child std streams to UTF-8 with lossless decoding.

    On Windows a piped stdout defaults to the locale codec (cp1252), which can
    raise on Unicode titles/album names before the parent ever sees the line.
    ``ensure_ascii`` payloads make this safety net redundant, but any stray
    ``print``/log sink remains UTF-8 clean.
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main() -> None:
    # Keep INFO chatter out of the protocol stream, but never lose a
    # warning/error: an unreported partial result looks like a clean fetch.
    _restore_child_stdio()
    _handler = _ProtocolHandler()
    _handler.setLevel(logging.WARNING)
    logging.basicConfig(level=logging.WARNING, handlers=[_handler], force=True)

    try:
        from spotdl.utils.spotify import SpotifyClient
        SpotifyClient.init(
            client_id=None,  # type: ignore[arg-type]
            client_secret=None,  # type: ignore[arg-type]
            user_auth=False,
            no_cache=True,
            headless=True,
        )
    except Exception as exc:
        _emit("__ERR__" + _safe_json("Spotify client init failed: %s" % exc) + "\n")
        sys.exit(1)

    from spotdl.utils.search import parse_query

    queries = sys.argv[1:]
    songs = []
    failed_queries = []
    for q in queries:
        try:
            songs.extend(parse_query(query=[q], threads=8))
        except KeyboardInterrupt:
            raise
        except BaseException as exc:
            failed_queries.append(q)
            _emit(
                "__WARN__"
                + _safe_json("Query failed: %s (%s)" % (q[:60], exc))
                + "\n"
            )

    for s in songs:
        payload = {
            "url": getattr(s, "url", "") or "",
            "artist": getattr(s, "artist", "") or "",
            "title": getattr(s, "name", "") or "",
            "album": getattr(s, "album_name", "") or "",
            "duration": getattr(s, "duration", 0) or 0,
        }
        _emit("__TRACK__" + _safe_json(payload) + "\n")

    _emit(
        "__DONE__"
        + _safe_json({"count": len(songs), "errors": len(failed_queries)})
        + "\n"
    )
    sys.exit(1 if (failed_queries and not songs) else 0)


if __name__ == "__main__":
    main()
