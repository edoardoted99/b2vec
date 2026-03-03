from django.core.signing import dumps, loads, BadSignature


SALT = 'company-id-v1'


def encode_id(pk: int) -> str:
    """Encode a numeric PK into an opaque URL-safe token."""
    return dumps(pk, salt=SALT)


def decode_id(token: str) -> int:
    """Decode a token back to the original PK. Raises Http404 on tamper."""
    from django.http import Http404
    try:
        return loads(token, salt=SALT)
    except BadSignature:
        raise Http404
