"""
embed.py -- a deliberately SIMPLE "stand-in" embedding model.

A real embedding model (for example all-MiniLM-L6-v2, 384 dimensions) is a
neural network trained on a huge amount of text. Downloading and running one
needs the internet and a lot of disk space, so the core of Lab 4 uses this tiny
substitute instead. It works like this:

  * a small hand-written lexicon groups words that mean the same thing
    ("twice", "duplicate", "double" -> concept DUPLICATE);
  * each concept has a fixed random 64-dimensional direction;
  * a text's vector is the sum of the directions of the concepts it mentions,
    plus a weak random direction for every other word, then scaled to length 1.

Texts that mention the same concepts end up pointing in similar directions, which
is the property that makes vector search work. What this stand-in CANNOT do is
understand language the way a trained model does: it only knows the words in its
lexicon. Part D of the lab shows how to swap in a real model.
"""
import re
import zlib

import numpy as np

DIM = 64

_NEUTRAL_WEIGHT = 0.2   # words outside the lexicon contribute only a little

_STOP = set("""a an and are as at be been but by did do does for from had has have he her his i if in into is it its
me my no not of on or our she so some than that the their them then there these they this to too us was we were
what when which who will with would you your however yet even though after before only""".split())

_CONCEPTS = {
    "duplicate": "twice two double duplicate repeated again once single".split(),
    "not_delivered": "received delivered delivery deliver arrive arrived nothing goods".split(),
    "amount_wrong": "smaller higher lower overcharged price agreed quoted figure receipt displayed till wrong".split(),
    "unauthorised": ("unauthorised authorised recognise unrecognised fraudulent stolen someone suspect sim swapped "
                     "initiate approve approved fraud").split(),
    "refund": "refund returned return back reversal credited cancelled overdue late promised".split(),
    "failed_debit": "failed fail unsuccessful error declined deducted deduct".split(),
}

_WORD_TO_CONCEPT = {w: c for c, words in _CONCEPTS.items() for w in words}


def _unit_vector(seed_text):
    rng = np.random.default_rng(zlib.crc32(seed_text.encode("utf-8")))
    v = rng.normal(size=DIM)
    return v / np.linalg.norm(v)


_CONCEPT_VECS = {c: _unit_vector("concept:" + c) for c in _CONCEPTS}


def tokenize(text):
    return re.findall(r"[a-z]+", text.lower())


def embed(text):
    """Return a unit-length numpy vector (float32) of DIM dimensions for `text`."""
    v = np.zeros(DIM)
    for tok in tokenize(text):
        if tok in _STOP:
            continue
        concept = _WORD_TO_CONCEPT.get(tok)
        if concept:
            v += _CONCEPT_VECS[concept]
        else:
            v += _NEUTRAL_WEIGHT * _unit_vector("word:" + tok)
    n = np.linalg.norm(v)
    if n == 0:
        v = _unit_vector("empty")
        n = 1.0
    return (v / n).astype(np.float32)


def to_pgvector(vec):
    """Format a vector as the text literal pgvector accepts, e.g. '[0.1,0.2,...]'."""
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"
