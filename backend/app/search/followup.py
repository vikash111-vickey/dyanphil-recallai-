"""Follow-up command parsing and session memory for Dyanphil."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass
class SessionState:
    """In-memory session state storing last results and recent messages."""

    last_results: List[Dict[str, Any]] = field(default_factory=list)
    messages: List[Dict[str, str]] = field(default_factory=list)  # max 10 messages
    shown_offset: int = 5
    last_active: float = field(default_factory=time.time)


_sessions: Dict[str, SessionState] = {}


def get_session(session_id: str) -> SessionState:
    """Retrieve or create session state by session_id."""
    if session_id not in _sessions:
        _sessions[session_id] = SessionState()
    sess = _sessions[session_id]
    sess.last_active = time.time()
    return sess


def record_message(session_id: str, role: str, message: str) -> None:
    """Record a message in the session history (kept to last 10)."""
    sess = get_session(session_id)
    sess.messages.append({"role": role, "message": message})
    if len(sess.messages) > 10:
        sess.messages = sess.messages[-10:]


def reset_sessions() -> None:
    """Clear all session states (used for testing)."""
    _sessions.clear()


# Follow-up regex patterns
RE_OPEN_FOLDER = re.compile(
    r"(?i)\b(?:open\s+(?:its\s+|the\s+)?folder|show\s+in\s+folder|reveal\s+in\s+folder|folder\s+kholo|iska\s+folder\s+kholo|directory\s+kholo)\b"
)

RE_OPEN_THIRD = re.compile(
    r"(?i)\b(?:open\s+(?:the\s+)?(?:third|3rd)(?:\s+one)?|(?:the\s+)?(?:third|3rd)\s+one|teesra\s+kholo|tisra\s+kholo|teesri\s+wali\s+kholo|tisri\s+wali\s+kholo|teesra\s+wala\s+kholo|tisra\s+wala\s+kholo)\b"
)

RE_OPEN_SECOND = re.compile(
    r"(?i)\b(?:open\s+(?:the\s+)?(?:second|2nd)(?:\s+one)?|(?:the\s+)?(?:second|2nd)\s+one|doosra\s+kholo|dusra\s+kholo|doosri\s+wali\s+kholo|dusri\s+wali\s+kholo|doosra\s+wala\s+kholo|dusra\s+wala\s+kholo)\b"
)

RE_OPEN_OLDER = re.compile(
    r"(?i)\b(?:(?:the\s+)?older\s+one|open\s+(?:the\s+)?older(?:\s+one)?|purana\s+wala(?:\s+kholo)?|purani\s+wali(?:\s+kholo)?)\b"
)

RE_OPEN_NEWER = re.compile(
    r"(?i)\b(?:(?:the\s+)?newer\s+one|open\s+(?:the\s+)?newer(?:\s+one)?|naya\s+wala(?:\s+kholo)?|nayi\s+wali(?:\s+kholo)?)\b"
)

RE_OPEN_FIRST = re.compile(
    r"(?i)\b(?:open\s+it|open\s+this|open\s+file|open\s+(?:the\s+)?(?:first|1st)(?:\s+one)?|(?:the\s+)?(?:first|1st)\s+one|kholo|isko\s+kholo|pehla\s+kholo|pehla\s+wala\s+kholo|pehli\s+wali\s+kholo|pehli\s+kholo|yeh\s+kholo|ye\s+kholo|file\s+kholo)\b"
)

RE_SHOW_MORE = re.compile(
    r"(?i)\b(?:show\s+more(?:\s+files)?|more(?:\s+files)?|show\s+next|next|aur\s+dikhao|aur\s+batao|aur\s+files(?:\s+dikhao)?)\b"
)


def detect_followup(text: str) -> Optional[Tuple[str, Any]]:
    """
    Detect whether user text is a follow-up action.
    Returns:
        ("open_folder", index)
        ("open_index", index)
        ("open_older", None)
        ("open_newer", None)
        ("show_more", None)
        None if not a follow-up.
    """
    clean = text.strip()
    if not clean:
        return None

    # Check for exact or regex command matches
    if RE_OPEN_FOLDER.search(clean):
        return ("open_folder", 0)

    if RE_OPEN_THIRD.search(clean):
        return ("open_index", 2)

    if RE_OPEN_SECOND.search(clean):
        return ("open_index", 1)

    if RE_OPEN_OLDER.search(clean):
        return ("open_older", None)

    if RE_OPEN_NEWER.search(clean):
        return ("open_newer", None)

    if RE_OPEN_FIRST.search(clean):
        return ("open_index", 0)

    # Simple isolated command check
    lower = clean.lower().strip("?!.,'\"")
    if lower in ("open", "kholo", "isko kholo", "pehla", "first"):
        return ("open_index", 0)
    if lower in ("second", "dusra", "doosra"):
        return ("open_index", 1)
    if lower in ("third", "tisra", "teesra"):
        return ("open_index", 2)
    if lower in ("folder", "folder kholo"):
        return ("open_folder", 0)
    if lower in ("more", "show more", "aur", "aur dikhao"):
        return ("show_more", None)

    if RE_SHOW_MORE.search(clean) and len(clean.split()) <= 4:
        return ("show_more", None)

    return None


def execute_followup(
    session: SessionState,
    action_type: str,
    action_arg: Any,
    tone: str,
    open_handler: Callable[[str, bool], Tuple[bool, str]],
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Execute a detected follow-up action against session memory:
    - Calls open_handler (same code as /open)
    - Replies in the tone composer's style
    Returns (reply_message, results_to_display).
    """
    results = session.last_results

    if not results and action_type != "show_more":
        if tone in ("urgent", "stressed"):
            return ("No previous results found to open. What document do you need?", [])
        if tone == "frustrated":
            return ("I don't have any recent search results in this session to open. What should I look for?", [])
        return ("There are no recent search results to open yet. What would you like to search for?", [])

    # 1. Open Folder
    if action_type == "open_folder":
        idx = action_arg if isinstance(action_arg, int) else 0
        if idx >= len(results):
            idx = 0
        target = results[idx]
        ok, msg = open_handler(target["path"], True)
        fname = target["filename"]
        if ok:
            if tone in ("urgent", "stressed"):
                reply = f"Opened folder containing {fname}."
            elif tone == "frustrated":
                reply = f"I've opened the folder containing {fname} for you."
            else:
                reply = f"Opening the folder for {fname}."
        else:
            if tone in ("urgent", "stressed"):
                reply = f"Could not open folder for {fname}: {msg}."
            elif tone == "frustrated":
                reply = f"I'm sorry, I couldn't open the folder for {fname}: {msg}."
            else:
                reply = f"Unable to open folder for {fname}: {msg}."
        return (reply, [target])

    # 2. Open Older / Newer
    if action_type in ("open_older", "open_newer"):
        sorted_res = sorted(results, key=lambda x: x.get("modified_at", 0))
        target = sorted_res[0] if action_type == "open_older" else sorted_res[-1]
        ok, msg = open_handler(target["path"], False)
        fname = target["filename"]
        descriptor = "older" if action_type == "open_older" else "newer"
        if ok:
            if tone in ("urgent", "stressed"):
                reply = f"Opened the {descriptor} file: {fname}."
            elif tone == "frustrated":
                reply = f"I've got the {descriptor} file open for you: {fname}."
            else:
                reply = f"Opening the {descriptor} document {fname} for you."
        else:
            reply = f"Could not open {fname}: {msg}."
        return (reply, [target])

    # 3. Open Specific Index (first/second/third)
    if action_type == "open_index":
        idx = action_arg
        if idx < 0 or idx >= len(results):
            ordinal = "first" if idx == 0 else ("second" if idx == 1 else "third")
            if tone in ("urgent", "stressed"):
                return (f"There is no {ordinal} file in your recent search results.", [])
            if tone == "frustrated":
                return (f"I only found {len(results)} file(s), so I couldn't open the {ordinal} one.", [])
            return (f"I couldn't find a {ordinal} file among the {len(results)} recent result(s).", [])

        target = results[idx]
        ok, msg = open_handler(target["path"], False)
        fname = target["filename"]
        if ok:
            if tone in ("urgent", "stressed"):
                reply = f"Opened {fname}."
            elif tone == "frustrated":
                reply = f"I've got it open for you now: {fname}."
            else:
                reply = f"Opening {fname} for you now."
        else:
            if tone in ("urgent", "stressed"):
                reply = f"Could not open {fname}: {msg}."
            elif tone == "frustrated":
                reply = f"I'm sorry, I couldn't open {fname}: {msg}."
            else:
                reply = f"Unable to open {fname}: {msg}."
        return (reply, [target])

    # 4. Show More
    if action_type == "show_more":
        offset = session.shown_offset
        more_slice = results[offset : offset + 5]
        if more_slice:
            session.shown_offset += len(more_slice)
            if tone in ("urgent", "stressed"):
                reply = f"Here are {len(more_slice)} more matching files."
            elif tone == "frustrated":
                reply = "Here are more matching files from your search."
            else:
                reply = f"Here are {len(more_slice)} additional matching documents."
            return (reply, more_slice)
        else:
            if tone in ("urgent", "stressed"):
                reply = "No additional results found for this search."
            elif tone == "frustrated":
                reply = "Those were all the matches found for your search."
            else:
                reply = "That's all the matching documents found for your search."
            return (reply, [])

    return ("I didn't recognize that follow-up request.", [])
