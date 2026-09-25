"""SDP sanitizer tests, pinned to a real Meta offer/answer pair.

The fixtures below are the exact SDPs captured when Meta rejected our answer with
code 138008; they are the regression anchor for the WhatsApp Calling interop fix.
"""

from __future__ import annotations

from voice.sdp import sanitize_answer, summarize

META_OFFER = """v=0
o=- 1787844148649 2 IN IP4 127.0.0.1
s=-
t=0 0
a=group:BUNDLE audio
a=msid-semantic: WMS bab5096d-91dc-4bcd-b471-604a6cb7a316
a=ice-lite
m=audio 3480 UDP/TLS/RTP/SAVPF 111 126
c=IN IP4 157.240.15.51
a=rtcp:9 IN IP4 0.0.0.0
a=candidate:2849191035 1 udp 2122260223 157.240.15.51 3480 typ host generation 0 network-cost 50
a=ice-ufrag:XqYWPLwCYgPvVLwD
a=ice-pwd:ylkwZfdMjMStntihfUybhg==
a=fingerprint:sha-256 F9:AF:20:F7:41:78:12:98:6A:59:19:FA:B2:18:92:87:3F:70:B9:A5:08:BB:15:5E:8D:BA:5A:5F:A4:72:0C:3E
a=setup:actpass
a=mid:audio
a=sendrecv
a=rtcp-mux
a=rtpmap:111 opus/48000/2
a=rtcp-fb:111 transport-cc
a=fmtp:111 maxaveragebitrate=20000;maxplaybackrate=16000;minptime=20;sprop-maxcapturerate=16000;useinbandfec=1
a=rtpmap:126 telephone-event/8000
a=maxptime:20
a=ptime:20
""".replace("\n", "\r\n")

AIORTC_ANSWER = """v=0
o=- 3996832952 3996832952 IN IP4 0.0.0.0
s=-
t=0 0
a=group:BUNDLE audio
a=msid-semantic:WMS *
m=audio 64991 UDP/TLS/RTP/SAVPF 111
c=IN IP4 10.4.2.2
a=sendrecv
a=mid:audio
a=rtcp:9 IN IP4 0.0.0.0
a=rtcp-mux
a=rtpmap:111 opus/48000/2
a=candidate:aaa 1 udp 2130706431 10.4.2.2 64991 typ host
a=candidate:bbb 1 udp 2130706431 fd7a:115c:a1e0::3237:a32f 64992 typ host
a=candidate:ccc 1 udp 2130706431 100.124.163.47 64993 typ host
a=candidate:ddd 1 udp 2130706431 192.168.8.113 64998 typ host
a=candidate:eee 1 udp 1694498815 45.139.226.101 36363 typ srflx raddr 10.4.2.2 rport 64991
a=end-of-candidates
a=ice-ufrag:CJwP
a=ice-pwd:8ZiPxtbCNG4auOLTHbExI7
a=fingerprint:sha-256 C7:F7:73:E4:79:13:FD:C9:88:93:C3:1E:45:31:BB:82:84:15:BD:F5:19:A6:CC:4F:25:4C:84:06:64:D2:6B:5F
a=fingerprint:sha-384 81:BC:E0:D1:9B:4B:95:1C
a=fingerprint:sha-512 28:78:CE:92:00:BA:57:0D
a=setup:active
""".replace("\n", "\r\n")


def _lines(sdp: str) -> list[str]:
    return sdp.replace("\r\n", "\n").strip().split("\n")


def test_only_the_sha256_fingerprint_survives() -> None:
    """The primary cause of Meta's 138008 rejection."""
    result = _lines(sanitize_answer(AIORTC_ANSWER, META_OFFER))

    fingerprints = [line for line in result if line.startswith("a=fingerprint:")]
    assert len(fingerprints) == 1
    assert fingerprints[0].startswith("a=fingerprint:sha-256 C7:F7:73")


def test_offer_codec_constraints_are_mirrored() -> None:
    result = _lines(sanitize_answer(AIORTC_ANSWER, META_OFFER))

    assert "a=rtcp-fb:111 transport-cc" in result
    assert any(line.startswith("a=fmtp:111 maxaveragebitrate=20000") for line in result)
    assert "a=ptime:20" in result
    assert "a=maxptime:20" in result
    # Mirrored attributes must sit inside the media section, after the rtpmap.
    assert result.index("a=rtcp-fb:111 transport-cc") > result.index("a=rtpmap:111 opus/48000/2")


def test_connection_line_uses_the_public_reflexive_address() -> None:
    result = _lines(sanitize_answer(AIORTC_ANSWER, META_OFFER))

    assert "c=IN IP4 45.139.226.101" in result
    assert "c=IN IP4 10.4.2.2" not in result


def test_unroutable_vpn_candidates_are_dropped_but_real_ones_kept() -> None:
    result = _lines(sanitize_answer(AIORTC_ANSWER, META_OFFER))
    candidates = [line for line in result if line.startswith("a=candidate:")]

    assert not any("100.124.163.47" in c for c in candidates)  # Tailscale CGNAT
    assert not any("fd7a:115c" in c for c in candidates)  # Tailscale IPv6
    assert any("192.168.8.113" in c for c in candidates)  # real LAN
    assert any("typ srflx" in c for c in candidates)  # public mapping — essential


def test_ice_credentials_and_setup_role_are_untouched() -> None:
    """Rewriting must never disturb what DTLS/ICE actually negotiated."""
    result = _lines(sanitize_answer(AIORTC_ANSWER, META_OFFER))

    assert "a=ice-ufrag:CJwP" in result
    assert "a=ice-pwd:8ZiPxtbCNG4auOLTHbExI7" in result
    assert "a=setup:active" in result
    assert "a=rtcp-mux" in result
    assert result[0] == "v=0"


def test_output_is_crlf_delimited() -> None:
    result = sanitize_answer(AIORTC_ANSWER, META_OFFER)

    assert result.endswith("\r\n")
    assert "\r\n" in result
    assert not result.replace("\r\n", "").__contains__("\n")


def test_summarize_reports_the_defects() -> None:
    assert "fingerprints=3" in summarize(AIORTC_ANSWER)
    assert "fingerprints=1" in summarize(sanitize_answer(AIORTC_ANSWER, META_OFFER))


def test_sanitizing_is_idempotent() -> None:
    once = sanitize_answer(AIORTC_ANSWER, META_OFFER)
    twice = sanitize_answer(once, META_OFFER)

    assert once == twice


AWS_ANSWER = """v=0
o=- 1 1 IN IP4 0.0.0.0
s=-
t=0 0
m=audio 41234 UDP/TLS/RTP/SAVPF 111
c=IN IP4 172.31.30.16
a=rtpmap:111 opus/48000/2
a=candidate:aaa 1 udp 2130706431 172.31.30.16 41234 typ host
a=candidate:bbb 1 udp 2130706431 2400:ff00::1 41235 typ host
a=fingerprint:sha-256 AA:BB
a=setup:active
""".replace("\n", "\r\n")


def test_private_host_candidates_are_relabelled_with_the_public_ip() -> None:
    """EC2 only sees its private address, so STUN is skipped and this stands in."""
    from voice.sdp import rewrite_host_candidates

    out = _lines(rewrite_host_candidates(AWS_ANSWER, "15.252.128.143"))

    assert any("15.252.128.143 41234 typ host" in line for line in out)
    assert not any("172.31.30.16" in line for line in out)
    assert "c=IN IP4 15.252.128.143" in out


def test_ipv6_candidates_are_left_alone() -> None:
    """IPv6 is globally routable; rewriting it to an IPv4 would break the line."""
    from voice.sdp import rewrite_host_candidates

    out = _lines(rewrite_host_candidates(AWS_ANSWER, "15.252.128.143"))

    assert any("2400:ff00::1 41235 typ host" in line for line in out)


def test_rewriting_leaves_ports_and_crypto_untouched() -> None:
    from voice.sdp import rewrite_host_candidates

    out = _lines(rewrite_host_candidates(AWS_ANSWER, "15.252.128.143"))

    assert "a=fingerprint:sha-256 AA:BB" in out
    assert "a=setup:active" in out
    assert any("m=audio 41234" in line for line in out)


def test_a_public_address_is_not_rewritten() -> None:
    """Only private (NAT-side) addresses are stand-ins for the public one."""
    from voice.sdp import rewrite_host_candidates

    already_public = AWS_ANSWER.replace("172.31.30.16", "13.13.13.13")
    out = _lines(rewrite_host_candidates(already_public, "15.252.128.143"))

    assert any("13.13.13.13 41234 typ host" in line for line in out)
