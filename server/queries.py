from starlette.datastructures import QueryParams


def strict_query(query: QueryParams, allowed: set[str]) -> dict[str, str]:
    if set(query) - allowed or any(len(query.getlist(key)) != 1 for key in query):
        raise ValueError("Unexpected or repeated query parameter.")
    return dict(query)


def query_int(value: str) -> int:
    if not value.isascii() or not value.isdecimal() or len(value) > 10:
        raise ValueError("Expected an int32.")
    number = int(value)
    if number > 2147483647:
        raise ValueError("Expected an int32.")
    return number
