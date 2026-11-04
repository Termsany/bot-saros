"""bot._secret_for_ccxt: an Ed25519 key given as one env line (base64 PKCS#8 DER) reaches ccxt as a PEM it signs with
EdDSA — checked by verifying ccxt's real signature with the public key — and an HMAC secret is left as it was."""
import base64, os, sys, unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse, unquote
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import ccxt
import bot


def der_b64(key):
    return base64.b64encode(key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption())).decode()


class Ed25519KeyTests(unittest.TestCase):
    def test_an_ed25519_line_is_signed_with_eddsa_by_ccxt(self):
        key = Ed25519PrivateKey.generate()
        line = der_b64(key)
        self.assertTrue(line.startswith(bot.ED25519_DER_B64_PREFIX)); self.assertEqual(len(line), 64)
        pem = bot._secret_for_ccxt(line)
        self.assertLessEqual(len(pem), 120)                      # ccxt: longer means RSA
        ex = ccxt.binanceusdm({"apiKey": "k" * 64, "secret": pem})
        sent = []
        ex.fetch = lambda url, method="GET", headers=None, body=None: sent.append(url) or {}   # never leaves the machine
        ex.fapiPrivateV2GetAccount()
        query = urlparse(sent[0]).query
        sig = parse_qs(query)["signature"][0]
        payload = query.split("&signature=")[0].encode()
        key.public_key().verify(base64.b64decode(unquote(sig)), payload)   # raises if it isn't an Ed25519 signature

    def test_an_hmac_secret_is_unchanged(self):
        hmac = "A1b2" * 16
        self.assertEqual(bot._secret_for_ccxt(hmac), hmac)

    def test_get_exchange_passes_the_converted_secret(self):
        line = der_b64(Ed25519PrivateKey.generate())
        old = {k: os.environ.get(k) for k in ("BINANCE_API_KEY", "BINANCE_SECRET", "CREDENTIALS_DIRECTORY")}
        try:
            os.environ.pop("CREDENTIALS_DIRECTORY", None)
            os.environ["BINANCE_API_KEY"] = "k" * 64; os.environ["BINANCE_SECRET"] = line
            ex, err = bot.get_exchange(auth=True)
            self.assertIsNone(err)
            self.assertTrue(ex.secret.startswith("-----BEGIN PRIVATE KEY-----"))
        finally:
            for k, v in old.items():
                if v is None: os.environ.pop(k, None)
                else: os.environ[k] = v


if __name__ == "__main__":
    unittest.main()
