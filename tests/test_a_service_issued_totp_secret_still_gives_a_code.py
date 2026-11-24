# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2190`. pyotp 2.12 refuses a TOTP secret under 112 bits unless told
otherwise. The vault does not choose these secrets: the service that issued the
login did, and 16 base32 characters (80 bits) is what most of them issue. The
vault's own floor is those 16 characters (`_clean_totp`), so a secret it
accepted must still give a code, whether typed, pasted as an otpauth:// link,
or read from Bitwarden."""
import pyotp
import pytest

from src import vault as V

SIXTEEN = "JBSWY3DPEHPK3PXP"  # 80 bits, the length most services issue


def test_a_sixteen_character_secret_gives_the_code_pyotp_would():
    code = V._code_now(SIXTEEN)
    assert len(code) == 6 and code.isdigit()

    class _Any(pyotp.TOTP):
        min_secret_length_bits = 0

    assert code == _Any(SIXTEEN).now()


def test_an_otpauth_link_with_a_sixteen_character_secret_is_read():
    uri = f"otpauth://totp/Example:alice?secret={SIXTEEN}&issuer=Example"
    assert V._clean_totp(uri) == SIXTEEN


def test_a_lower_case_or_spaced_secret_in_a_link_is_read_the_same():
    uri = "otpauth://totp/Example:alice?issuer=Example&secret=jbsw y3dp ehpk 3pxp"
    assert V._clean_totp(uri.replace(" ", "%20")) == SIXTEEN


@pytest.mark.parametrize("uri", [
    "otpauth://totp/Example:alice?issuer=Example",
    f"otpauth://totp/x?secret={SIXTEEN}&secret={SIXTEEN}",
    "otpauth://totp/x?secret=not-base32",
])
def test_a_link_without_one_readable_secret_is_refused_with_a_sentence(uri):
    with pytest.raises(V.VaultRefused):
        V._clean_totp(uri)


def test_the_vault_floor_is_still_sixteen_characters():
    with pytest.raises(V.VaultRefused):
        V._clean_totp("JBSWY3DPEHPK3PX")
