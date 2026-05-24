"""Deterministic speech/conversation metrics computed from a call transcript.

Pure-Python, no LLM — these are the hard numbers that complement Gemma's
qualitative scoring. Outputs the same shape every time so the UI can chart
deltas over weeks.

Usage:
    from metrics import compute_metrics
    m = compute_metrics(history)  # history = [{"role":"user"|"assistant", "content":...}]
    # m -> {"talk_ratio": 0.42, "filler_count": 9, "fillers": {"um": 3, ...},
    #       "question_ratio": 0.28, "longest_monologue_words": 84, ...}

The transcript convention:
    role="user"      → the salesperson (rep) speaking
    role="assistant" → the buyer / persona speaking
"""
from __future__ import annotations
import re
from collections import Counter

# Words that signal hedging or low confidence. Tuned to spoken-call patterns,
# not formal writing — "like" and "you know" are the big offenders for SDRs.
FILLER_WORDS = [
    "um", "uh", "er", "ah", "hmm", "mm",
    "like", "literally", "basically", "actually", "honestly", "obviously",
    "you know", "i mean", "kind of", "kinda", "sort of", "sorta", "right?",
    "i guess", "sort of like", "kind of like", "or whatever", "or something",
    "to be honest", "to be fair",
]

# Hedge phrases (separate from fillers — these specifically weaken claims)
HEDGE_PHRASES = [
    "i think", "i feel like", "maybe", "perhaps", "kind of", "sort of",
    "i was wondering if", "would it be possible", "if it's not too much trouble",
    "i don't know if",
]


def compute_metrics(history: list[dict]) -> dict:
    """Compute all metrics in one pass. Returns a flat dict for easy JSON output."""
    rep_turns = [m["content"] for m in history if m.get("role") == "user"]
    buyer_turns = [m["content"] for m in history if m.get("role") == "assistant"]

    rep_text = " ".join(rep_turns)
    buyer_text = " ".join(buyer_turns)

    rep_words = _word_count(rep_text)
    buyer_words = _word_count(buyer_text)
    total_words = rep_words + buyer_words

    fillers = _count_phrases(rep_text, FILLER_WORDS)
    hedges = _count_phrases(rep_text, HEDGE_PHRASES)

    rep_questions = sum(_question_count(t) for t in rep_turns)
    rep_statements = max(1, len(rep_turns)) - rep_questions

    sentences = _split_sentences(rep_text)
    avg_sentence = sum(_word_count(s) for s in sentences) / max(1, len(sentences))
    longest_monologue = max((_word_count(t) for t in rep_turns), default=0)

    talk_ratio = rep_words / total_words if total_words else 0.0

    return {
        "talk_ratio": round(talk_ratio, 3),
        "rep_words": rep_words,
        "buyer_words": buyer_words,
        "total_turns": len(history),
        "rep_turns": len(rep_turns),
        "buyer_turns": len(buyer_turns),
        "rep_questions": rep_questions,
        "rep_statements": max(0, rep_statements),
        "question_ratio": round(rep_questions / max(1, len(rep_turns)), 3),
        "fillers": dict(fillers),
        "filler_count": sum(fillers.values()),
        "fillers_per_100_words": round(sum(fillers.values()) / max(1, rep_words) * 100, 2),
        "hedge_count": sum(hedges.values()),
        "hedges": dict(hedges),
        "avg_sentence_words": round(avg_sentence, 1),
        "longest_monologue_words": longest_monologue,
        "coaching_signals": _coaching_signals({
            "talk_ratio": talk_ratio,
            "question_ratio": rep_questions / max(1, len(rep_turns)),
            "filler_count": sum(fillers.values()),
            "hedge_count": sum(hedges.values()),
            "longest_monologue": longest_monologue,
            "rep_turns": len(rep_turns),
        }),
    }


def compute_text_metrics(transcript: str) -> dict:
    """Metrics on a raw transcript without speaker labels (real whisper output).

    Less useful than the role-aware version since we can't compute talk ratio,
    but still surfaces fillers, hedges, question count, and pace — enough to
    coach against on real recorded calls.
    """
    if not transcript or not transcript.strip():
        return {"empty": True}
    fillers = _count_phrases(transcript, FILLER_WORDS)
    hedges = _count_phrases(transcript, HEDGE_PHRASES)
    sentences = _split_sentences(transcript)
    total_words = _word_count(transcript)
    questions = transcript.count("?")
    return {
        "total_words": total_words,
        "sentences": len(sentences),
        "questions": questions,
        "filler_count": sum(fillers.values()),
        "fillers": dict(fillers),
        "fillers_per_100_words": round(sum(fillers.values()) / max(1, total_words) * 100, 2),
        "hedge_count": sum(hedges.values()),
        "hedges": dict(hedges),
        "avg_sentence_words": round(sum(_word_count(s) for s in sentences) / max(1, len(sentences)), 1),
        "coaching_signals": _coaching_signals_text({
            "filler_count": sum(fillers.values()),
            "hedge_count": sum(hedges.values()),
            "questions": questions,
            "total_words": total_words,
        }),
    }


def _coaching_signals_text(m: dict) -> list[str]:
    """Coaching for transcripts without speaker labels — focuses on filler/hedge
    flags since we can't compute talk ratio or per-speaker question rate."""
    out = []
    if m["filler_count"] >= 8:
        out.append(f"{m['filler_count']} filler words across the call — 'like', 'um', 'basically' weaken authority.")
    if m["hedge_count"] >= 5:
        out.append(f"{m['hedge_count']} hedge phrases — 'I think', 'maybe' shrink your claims.")
    if m["questions"] < 5 and m["total_words"] > 400:
        out.append(f"Only {m['questions']} questions across {m['total_words']} words — discovery calls need 11-14 questions.")
    return out


def _word_count(text: str) -> int:
    """Count whitespace-separated tokens. Strips punctuation for accuracy."""
    if not text:
        return 0
    return len(re.findall(r"\b[\w']+\b", text))


def _count_phrases(text: str, phrases: list[str]) -> Counter:
    """Case-insensitive phrase counter using word-boundary regex."""
    counter = Counter()
    low = text.lower()
    for phrase in phrases:
        pattern = r"\b" + re.escape(phrase) + r"\b"
        n = len(re.findall(pattern, low))
        if n:
            counter[phrase] = n
    return counter


def _question_count(text: str) -> int:
    """Count question marks — better than parsing 'wh-' starts which miss tag questions."""
    return text.count("?")


def _split_sentences(text: str) -> list[str]:
    """Naive sentence split — periods/!/? followed by whitespace or end. Good enough."""
    if not text:
        return []
    parts = re.split(r"[.!?]+\s+", text)
    return [p.strip() for p in parts if p.strip()]


def _coaching_signals(m: dict) -> list[str]:
    """Plain-language flags for the UI to surface. Keep these specific and actionable —
    a flag the rep can fix in their next call, not a vague 'be better'.

    Thresholds tuned against research on B2B sales call patterns: top-quartile
    reps run a 43% talk ratio, ask 11-14 questions, and have <2 fillers per 100
    words. We flag anything 1.5x worse than that baseline."""
    out = []
    tr = m["talk_ratio"]
    if tr > 0.65 and m["rep_turns"] >= 4:
        out.append(f"You talked {int(tr*100)}% of the time — top reps stay near 43%. Ask more, tell less.")
    elif tr < 0.20 and m["rep_turns"] >= 4:
        out.append(f"You only talked {int(tr*100)}% — you may be too passive. Take more control of the agenda.")

    qr = m["question_ratio"]
    if qr < 0.20 and m["rep_turns"] >= 4:
        out.append(f"Only {int(qr*100)}% of your turns were questions — top reps ask 11-14 questions per discovery call.")

    if m["filler_count"] >= 8:
        out.append(f"{m['filler_count']} filler words — 'like', 'um', 'basically' weaken authority. Replace with silence.")

    if m["hedge_count"] >= 5:
        out.append(f"{m['hedge_count']} hedge phrases — 'I think', 'maybe' shrink your claims. State them directly.")

    if m["longest_monologue"] > 100:
        out.append(f"Your longest turn was {m['longest_monologue']} words — anything over 80 loses the buyer. Break it up with a check-in question.")

    return out
