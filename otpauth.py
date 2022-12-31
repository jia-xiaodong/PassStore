# -*- coding: utf-8 -*-
"""
    otpauth
    ~~~~~~~

    Implements two-step verification of HOTP/TOTP.

    :copyright: (c) 2013 - 2015 by Hsiaoming Yang.
    :license: BSD, see LICENSE for more details.
"""
import time
import hmac
import base64
import struct
import hashlib
import warnings


class OtpAuth:
    """One Time Password Authentication.

    :param secret: A secret token for the authentication, which has been Base32-encoded.
    """

    def __init__(self, secret: str):
        self.secret = secret

    def hotp(self, counter=4):
        """Generate a HOTP code.

        :param counter: HOTP is a counter based algorithm.
        """
        return generate_hotp(self.secret, counter)

    def totp(self, period=30, timestamp=None):
        """Generate a TOTP code.

        A TOTP code is an extension of HOTP algorithm.

        :param period: A period that a TOTP code is valid in seconds
        :param timestamp: Create TOTP at this given timestamp
        :return: tuple(passcode, remaining seconds)
        """
        return generate_totp(self.secret, period, timestamp)

    def valid_hotp(self, code, last=0, trials=100):
        """Valid a HOTP code.

        :param code: A number that is less than 6 characters.
        :param last: Guess HOTP code from last + 1 range.
        :param trials: Guest HOTP code end at last + trials + 1.
        """
        if not valid_code(code):
            return False

        code = bytes(int(code))
        for i in range(last + 1, last + trials + 1):
            if compare_digest(bytes(self.hotp(counter=i)), code):
                return i
        return False

    def valid_totp(self, code, period=30, timestamp=None):
        """Valid a TOTP code.

        :param code: A number that is less than 6 characters.
        :param period: A period that a TOTP code is valid in seconds
        :param timestamp: Validate TOTP at this given timestamp
        """
        if not valid_code(code):
            return False
        return compare_digest(
            bytes(self.totp(period, timestamp)),
            bytes(int(code))
        )

    @staticmethod
    def encoded_secret(secret: bytes):
        secret = base64.b32encode(secret)
        secret = secret.decode('utf-8')
        return secret.strip('=')  # remove pad string

    def to_uri(self, type, label, issuer, counter=None):
        """Generate the otpauth protocal string.

        :param type: Algorithm type, hotp or totp.
        :param label: Label of the identifier.
        :param issuer: The company, the organization or something else.
        :param counter: Counter of the HOTP algorithm.
        """
        type = type.lower()

        if type not in ('hotp', 'totp'):
            raise ValueError('type must be hotp or totp')

        if type == 'hotp' and not counter:
            raise ValueError('HOTP type authentication need counter')

        # https://code.google.com/p/google-authenticator/wiki/KeyUriFormat
        url = ('otpauth://%(type)s/%(label)s?secret=%(secret)s'
               '&issuer=%(issuer)s')
        dct = dict(
            type=type, label=label, issuer=issuer,
            secret=self.secret, counter=counter
        )
        ret = url % dct
        if type == 'hotp':
            ret = '%s&counter=%s' % (ret, counter)
        return ret

    def to_google(self, type, label, issuer, counter=None):
        """Generate the otpauth protocal string for Google Authenticator.

        .. deprecated:: 0.2.0
           Use :func:`to_uri` instead.
        """
        warnings.warn('deprecated, use to_uri instead', DeprecationWarning)
        return self.to_uri(type, label, issuer, counter)


def generate_hotp(secret: str, counter=4):
    """Generate a HOTP code.

    :param secret: A secret token for the authentication.
    :param counter: HOTP is a counter based algorithm.
    """
    # https://tools.ietf.org/html/rfc4226
    msg = struct.pack('>Q', counter)
    digest = hmac.digest(base64.b32decode(secret), msg, hashlib.sha1)
    pos = digest[19] & 0x0f
    base = struct.unpack('>I', digest[pos:pos + 4])[0] & 0x7fffffff
    token = base % 1000000
    return '%06d' % token


def generate_totp(secret: str, period=30, timestamp=None):
    """Generate a TOTP code.

    A TOTP code is an extension of HOTP algorithm.

    :param secret: A secret token for the authentication.
    :param period: A period that a TOTP code is valid in seconds
    :param timestamp: Current time stamp.

    :return: tuple(passcode, remaining seconds)
    """
    if timestamp is None:
        timestamp = time.time()
    counter = int(timestamp) // period
    remaining_seconds = period - int(timestamp) % period
    return generate_hotp(secret, counter), remaining_seconds


def to_bytes(text: str):
    return text.encode('utf-8')


def valid_code(code: int):
    code = str(code)
    return code.isdigit() and len(code) <= 6


def compare_digest(a, b):
    func = getattr(hmac, 'compare_digest', None)
    if func:
        return func(a, b)

    # fallback
    if len(a) != len(b):
        return False

    rv = 0
    for x, y in zip(a, b):
        rv |= x ^ y
    return rv == 0


if __name__ == '__main__':
    auth = OtpAuth('IJKQGLQ5S3DYG3XLQO7VPPSJ2SYIS5VP')
    code = auth.totp()
    print(code)
