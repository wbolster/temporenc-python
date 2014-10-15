
import collections
import struct
import sys


PY2 = sys.version_info[0] == 2
PY3 = sys.version_info[0] == 3

#
# Compatibility helpers
#

# struct.unpack() does not handle bytearray() in Python < 2.7
if sys.version_info[:2] <= (2, 6):
    def unpack(fmt, value):
        return struct.unpack(fmt, buffer(value))
else:
    unpack = struct.unpack

if PY2:
    def to_bytes(value, size):
        if size <= 8:
            return struct.pack('>Q', value)[-size:]

        if size <= 10:
            return struct.pack(
                '>HQ',
                (value >> 64) & 0xffff,
                value & 0xffffffffffffffff)[-size:]

        # Temporenc values are always 3-10 bytes.
        assert False, "value too large"

    def from_bytes(value):
        raise NotImplementedError()

else:
    def to_bytes(value, size):
        return value.to_bytes(size, 'big')

    from_bytes = int.from_bytes


#
# Components descriptions
#
# Composite components like date and time are
# split to make the implementation simpler. Each component is a tuple
# with these components:
#
#   (name, size, mask, min_value, max_value, empty)
#

COMPONENT_YEAR = ('year', 12, 0xfff, 0, 4094, 4095)
COMPONENT_MONTH = ('month', 4, 0xf, 0, 11, 15)
COMPONENT_DAY = ('day', 5, 0x1f, 0, 30, 31)
COMPONENT_HOUR = ('hour', 5, 0x1f, 0, 23, 31)
COMPONENT_MINUTE = ('minute', 6, 0x3f, 0, 59, 63)
COMPONENT_SECOND = ('second', 6, 0x3f, 0, 60, 63)
COMPONENT_MILLISECOND = ('millisecond', 10, 0x3ff, 0, 999, None)
COMPONENT_MICROSECOND = ('microsecond', 20, 0xfffff, 0, 999999, None)
COMPONENT_NANOSECOND = ('nanosecond', 30, 0x3fffffff, 0, 999999999, None)
COMPONENT_PADDING_2 = ('padding', 2, 0x2, 0, 0, None)
COMPONENT_PADDING_4 = ('padding', 4, 0x4, 0, 0, None)
COMPONENT_PADDING_6 = ('padding', 6, 0x6, 0, 0, None)

#
# Type descriptions
#
# These are (size, components) tuples
#

SUPPORTED_TYPES = set(['D', 'T', 'DT', 'DTZ', 'DTS', 'DTSZ'])
TYPES = {
    'D': (COMPONENT_YEAR, COMPONENT_MONTH, COMPONENT_DAY),
    'T': (COMPONENT_HOUR, COMPONENT_MINUTE, COMPONENT_SECOND),
    'DT': (COMPONENT_YEAR, COMPONENT_MONTH, COMPONENT_DAY,
           COMPONENT_HOUR, COMPONENT_MINUTE, COMPONENT_SECOND),
    'DTZ': (),  # TODO
    'DTS-10': (COMPONENT_YEAR, COMPONENT_MONTH, COMPONENT_DAY,
               COMPONENT_HOUR, COMPONENT_MINUTE, COMPONENT_SECOND,
               COMPONENT_MILLISECOND, COMPONENT_PADDING_4),
    'DTS-20': (COMPONENT_YEAR, COMPONENT_MONTH, COMPONENT_DAY,
               COMPONENT_HOUR, COMPONENT_MINUTE, COMPONENT_SECOND,
               COMPONENT_MICROSECOND, COMPONENT_PADDING_2),
    'DTS-30': (COMPONENT_YEAR, COMPONENT_MONTH, COMPONENT_DAY,
               COMPONENT_HOUR, COMPONENT_MINUTE, COMPONENT_SECOND,
               COMPONENT_NANOSECOND),
    'DTS-0': (COMPONENT_YEAR, COMPONENT_MONTH, COMPONENT_DAY,
              COMPONENT_HOUR, COMPONENT_MINUTE, COMPONENT_SECOND,
              COMPONENT_PADDING_6),
    'DTSZ': (),  # TODO,
}

# Magic values indicating empty parts
YEAR_EMPTY = 4095
MONTH_EMPTY = 15
DAY_EMPTY = 31
HOUR_EMPTY = 31
MINUTE_EMPTY = 63
SECOND_EMPTY = 63


Value = collections.namedtuple('Value', [
    'year', 'month', 'day', 'hour', 'minute', 'second'])


def packb(
        type=None,
        year=None, month=None, day=None,
        hour=None, minute=None, second=None,
        millisecond=None, microsecond=None, nanosecond=None):
    """
    Pack date and time information into a byte string.

    :return: encoded temporenc value
    :rtype: bytes
    """

    if type not in SUPPORTED_TYPES:
        raise ValueError("invalid temporenc type: {0!r}".format(type))

    # Month and day are stored off-by-one.
    if month is not None:
        month -= 1
    if day is not None:
        day -= 1

    padding = 0
    kwargs = locals()  # ugly, but it works :)

    # Byte packing
    if type == 'D':
        typespec = TYPES['D']
        n = 0b100
        bits_used = 3

    elif type == 'T':
        typespec = TYPES['T']
        n = 0b1010000
        bits_used = 7

    elif type == 'DT':
        typespec = TYPES['DT']
        n = 0b00
        bits_used = 2

    elif type == 'DTS':
        bits_used = 4  # combined type tag and precision tag
        if nanosecond is not None:
            n = 0b0110
            typespec = TYPES['DTS-30']
        elif microsecond is not None:
            n = 0b0101
            typespec = TYPES['DTS-20']
        elif millisecond is not None:
            n = 0b0100
            typespec = TYPES['DTS-10']
        else:
            n = 0b0111
            typespec = TYPES['DTS-0']

    # Pack the components
    for name, size, mask, min_value, max_value, empty in typespec:
        value = kwargs[name]

        if value is None:
            value = empty
        elif not min_value <= value <= max_value:
            raise ValueError(
                "{0} {1:d} not in range [{2:d}, {3:d}]".format(
                    name, value, min_value, max_value))

        bits_used += size
        n <<= size
        n |= value

    assert bits_used % 8 == 0  # FIXME remove once all types are implemented
    return to_bytes(n, bits_used // 8)


def unpackb(value):
    if not 3 <= len(value) <= 10:
        raise ValueError("value must be between 3 and 10 bytes")

    # Individual bytes should be integers.
    if PY2:
        value = bytearray(value)

    # Detect the type and convert the value into a number
    first = value[0]

    if first <= 0b00111111:  # tag 00
        typespec = TYPES['DT']
        value = value.rjust(8, b'\x00')
        (n,) = unpack('>Q', value.rjust(8, b'\x00'))

    elif first <= 0b01111111:  # tag 01
        raise NotImplementedError("DTS")

    elif first <= 0b10011111:  # tag 100
        typespec = TYPES['D']
        (n,) = unpack('>L', bytes(value.rjust(4, b'\x00')))

    elif first <= 0b10100001:  # tag 1010000
        typespec = TYPES['T']
        (n,) = unpack('>L', bytes(value.rjust(4, b'\x00')))

    elif first <= 0b10111111:
        raise ValueError("first byte does not contain a valid tag")

    elif first <= 0b11011111:  # tag 110
        raise NotImplementedError("DTZ")

    elif first <= 0b11111111:  # tag 111
        raise NotImplementedError("DTSZ")

    # Iteratively shift off components from the numerical value
    kwargs = dict.fromkeys(Value._fields)
    for name, size, mask, min_value, max_value, empty in reversed(typespec):
        decoded = n & mask

        if decoded == empty:
            continue

        if not min_value <= decoded <= max_value:
            raise ValueError(
                "{0} {1:d} not in range [{2:d}, {3:d}]".format(
                    name, decoded, min_value, max_value))

        kwargs[name] = decoded
        n >>= size

    # Both month and day are stored off-by-one.
    if kwargs['month'] is not None:
        kwargs['month'] += 1
    if kwargs['day'] is not None:
        kwargs['day'] += 1

    return Value(**kwargs)
