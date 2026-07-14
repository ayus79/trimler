from app.database.postgres_client import PostgresClient

ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
BASE = len(ALPHABET)


def encode_base62(number: int) -> str:
    """Encode a non-negative integer into a base62 string."""
    if number < 0:
        raise ValueError("cannot base62-encode a negative number")
    if number == 0:
        return ALPHABET[0]

    digits = []
    while number > 0:
        number, remainder = divmod(number, BASE)
        digits.append(ALPHABET[remainder])
    return "".join(reversed(digits))


def decode_base62(code: str) -> int:
    """Decode a base62 string back into its integer value."""
    number = 0
    for char in code:
        index = ALPHABET.find(char)
        if index == -1:
            raise ValueError(f"invalid base62 character: {char!r}")
        number = number * BASE + index
    return number


async def generate_short_code(client: PostgresClient) -> tuple[int, str]:
    """Pulls the next value from urls_id_seq (the same sequence backing
    urls.id) and base62-encodes it, so the generated code always matches
    the row's own primary key with zero collision risk - no retry loop
    needed, unlike a randomly generated code.

    Returns:
        tuple[int, str]: (next_id, short_code) - pass next_id explicitly as
        the row's id on insert so it stays in sync with the encoded code.
    """
    next_id = await client.fetch_value("SELECT nextval('urls_id_seq')")
    return next_id, encode_base62(next_id)
