"""Make aiortc's SDP answer acceptable to WhatsApp's Calling API.

aiortc emits a standards-legal answer that Meta's validator rejects with an
opaque ``code 138008 "Provided SDP is invalid"``. Comparing a captured
offer/answer pair (voice_sdp_debug.log) shows three concrete divergences:

1. **Three fingerprint lines** (sha-256, sha-384, sha-512). RFC 8122 permits
   several, but every WebRTC stack in practice sends exactly one and Meta's
   parser chokes on the extras. This is the primary rejection cause.
2. **No ``a=fmtp``/``a=rtcp-fb``/``a=ptime``** echo. Meta's offer pins Opus to
   16 kHz capture, 20 ms ptime and transport-cc; an answer that silently drops
   those constraints does not mirror the offer.
3. **``c=`` line carries a private address** (the bound interface) instead of
   the server-reflexive address, so Meta sees an unroutable connection line.

Sanitising the string we *send* is deliberate: aiortc keeps its own unmodified
local description, so DTLS/ICE behaviour is untouched — Meta simply verifies our
certificate against the sha-256 fingerprint, which is the one it always used.
"""

from __future__ import annotations

# Provably unroutable from Meta's edge: Tailscale's CGNAT range and its IPv6
# ULA prefix. Advertising them only slows connectivity checks.
_UNROUTABLE_PREFIXES = ("100.64.", "100.65.", "100.124.", "fd7a:115c")


def _split(sdp: str) -> list[str]:
    return sdp.replace("\r\n", "\n").split("\n")


def _join(lines: list[str]) -> str:
    # SDP is CRLF-delimited; keep a trailing CRLF like aiortc does.
    body = "\r\n".join(line for line in lines if line != "")
    return body + "\r\n"


def _offer_media_attrs(offer_sdp: str, payload: str) -> list[str]:
    """Pull the fmtp/rtcp-fb/ptime lines the offer set for this payload type."""
    wanted: list[str] = []
    for line in _split(offer_sdp):
        if line.startswith((f"a=fmtp:{payload} ", f"a=rtcp-fb:{payload} ")):
            wanted.append(line)
        elif line.startswith(("a=ptime:", "a=maxptime:")):
            wanted.append(line)
    return wanted


def _srflx_address(lines: list[str]) -> str | None:
    """The public IPv4 the answer's server-reflexive candidate maps to."""
    for line in lines:
        if "typ srflx" in line:
            parts = line.split()
            # a=candidate:<foundation> <comp> <proto> <pri> <ip> <port> typ srflx ...
            if len(parts) > 5 and ":" not in parts[4]:
                return parts[4]
    return None


def _is_unroutable_candidate(line: str) -> bool:
    parts = line.split()
    if len(parts) < 8 or parts[7] != "host":
        return False
    address = parts[4]
    return address.startswith(_UNROUTABLE_PREFIXES)


def rewrite_host_candidates(sdp: str, public_ip: str) -> str:
    """Publish a known public IPv4 instead of the bound private address.

    EC2 is 1:1 NAT: the instance only ever sees its private address, so aiortc
    must ask a STUN server what its public address is, and because aiortc gathers
    ICE non-trickle the whole answer waits on that round trip (measured at ~5s).
    When the public IP is known up front, STUN can be skipped entirely and the
    host candidates relabelled here, which removes that wait from every call.

    Only IPv4 host candidates are rewritten; IPv6 is globally routable already and
    srflx/relay candidates carry addresses STUN/TURN discovered.
    """
    out: list[str] = []
    for line in _split(sdp):
        if line.startswith("a=candidate:"):
            parts = line.split()
            if len(parts) > 7 and parts[7] == "host" and _is_private_ipv4(parts[4]):
                parts[4] = public_ip
                out.append(" ".join(parts))
                continue
        if line.startswith("c=IN IP4 "):
            out.append(f"c=IN IP4 {public_ip}")
            continue
        out.append(line)
    return _join(out)


def _is_private_ipv4(address: str) -> bool:
    if ":" in address:
        return False
    octets = address.split(".")
    if len(octets) != 4 or not all(o.isdigit() for o in octets):
        return False
    first, second = int(octets[0]), int(octets[1])
    return first == 10 or (first == 172 and 16 <= second <= 31) or (first == 192 and second == 168) or first == 127


def sanitize_answer(answer_sdp: str, offer_sdp: str) -> str:
    """Return an answer Meta accepts, preserving aiortc's ICE/DTLS material."""
    lines = _split(answer_sdp)
    payload = _negotiated_payload(lines)
    srflx = _srflx_address(lines)
    # Compare against the whole answer, not just the lines emitted so far: ptime
    # attributes live *below* the rtpmap, so an "already emitted?" check would
    # duplicate them on a second pass and make sanitising non-idempotent.
    existing = set(lines)
    extra_attrs = [attr for attr in _offer_media_attrs(offer_sdp, payload) if attr not in existing] if payload else []

    out: list[str] = []
    seen_fingerprint = False
    for line in lines:
        if line.startswith("a=fingerprint:"):
            # Keep the first sha-256 fingerprint only.
            if seen_fingerprint or not line.startswith("a=fingerprint:sha-256"):
                continue
            seen_fingerprint = True
            out.append(line)
            continue

        if line.startswith("a=candidate:") and _is_unroutable_candidate(line):
            continue

        if line.startswith("c=IN IP4 ") and srflx:
            out.append(f"c=IN IP4 {srflx}")
            continue

        out.append(line)

        # Mirror the offer's codec constraints right after the rtpmap.
        if payload and line.startswith(f"a=rtpmap:{payload} "):
            out.extend(extra_attrs)

    return _join(out)


def _negotiated_payload(lines: list[str]) -> str | None:
    """First payload type on the answer's audio m-line."""
    for line in lines:
        if line.startswith("m=audio "):
            parts = line.split()
            if len(parts) > 3:
                return parts[3]
    return None


def summarize(sdp: str) -> str:
    """Compact one-line description for logs (codecs, candidate count, setup)."""
    lines = _split(sdp)
    codecs = [line.split()[1] for line in lines if line.startswith("a=rtpmap:")]
    candidates = sum(1 for line in lines if line.startswith("a=candidate:"))
    fingerprints = sum(1 for line in lines if line.startswith("a=fingerprint:"))
    setup = next((line.split(":", 1)[1] for line in lines if line.startswith("a=setup:")), "?")
    return f"codecs={','.join(codecs)} candidates={candidates} fingerprints={fingerprints} setup={setup}"
