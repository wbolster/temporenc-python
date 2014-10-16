
import collections
import struct
import sys


PY2 = sys.version_info[0] == 2
PY3 = sys.version_info[0] == 3

#
# Byte packing helpers
#

pack_4 = struct.Struct('>L').pack
pack_8 = struct.Struct('>Q').pack
pack_2_8 = struct.Struct('>HQ').pack


def unpack_4(value, _unpack=struct.Struct('>L').unpack):
    return _unpack(value.rjust(4, b'\x00'))[0]


def unpack_8(value, _unpack=struct.Struct('>Q').unpack):
    return _unpack(value.rjust(8, b'\x00'))[0]


#
# Components and types
#
# Composite components like date and time are split to make the
# implementation simpler. Each component is a tuple with these
# components:
#
#   (name, size, mask, min_value, max_value, empty)
#

YEAR_MIN, YEAR_MAX, YEAR_EMPTY, YEAR_MASK = 0, 4094, 4095, 0xfff
MONTH_MIN, MONTH_MAX, MONTH_EMPTY, MONTH_MASK = 0, 11, 15, 0xf
DAY_MIN, DAY_MAX, DAY_EMPTY, DAY_MASK = 0, 30, 31, 0x1f
HOUR_MIN, HOUR_MAX, HOUR_EMPTY, HOUR_MASK = 0, 23, 31, 0x1f
MINUTE_MIN, MINUTE_MAX, MINUTE_EMPTY, MINUTE_MASK = 0, 59, 63, 0x3f
SECOND_MIN, SECOND_MAX, SECOND_EMPTY, SECOND_MASK = 0, 60, 63, 0x3f
MILLISECOND_MIN, MILLISECOND_MAX, MILLISECOND_MASK = 0, 999, 0x3ff
MICROSECOND_MIN, MICROSECOND_MAX, MICROSECOND_MASK = 0, 999999, 0xfffff
NANOSECOND_MIN, NANOSECOND_MAX, NANOSECOND_MASK = 0, 999999999, 0x3fffffff

SUPPORTED_TYPES = set(['D', 'T', 'DT', 'DTZ', 'DTS', 'DTSZ'])

D_MASK = 0x1fffff
T_MASK = 0x1ffff


#
# Public API
#

Value = collections.namedtuple('Value', [
    'year', 'month', 'day',
    'hour', 'minute', 'second',
    'millisecond', 'microsecond', 'nanosecond',
    'tz_hour', 'tz_minute', 'tz_offset'])


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

    #
    # Type detection
    #

    if type is None:
        has_d = not (year is None and month is None and day is None)
        has_t = not (hour is None and minute is None and second is None)
        has_s = not (millisecond is None and microsecond is None
                     and nanosecond is None)

        if has_s:
            type = 'DTS'
        elif has_d and has_t:
            type = 'DT'
        elif has_d:
            type = 'D'
        elif has_t:
            type = 'T'
        else:
            # No information at all, just use the smallest type
            type = 'D'

    elif type not in SUPPORTED_TYPES:
        raise ValueError("invalid temporenc type: {0!r}".format(type))

    #
    # Value checking
    #

    if year is None:
        year = YEAR_EMPTY
    elif not YEAR_MIN <= year <= YEAR_MAX:
        raise ValueError("'year' not within supported range")

    if month is None:
        month = MONTH_EMPTY
    else:
        month -= 1
        if not MONTH_MIN <= month <= MONTH_MAX:
            raise ValueError("'month' not within supported range")

    if day is None:
        day = DAY_EMPTY
    else:
        day -= 1
        if not DAY_MIN <= day <= DAY_MAX:
            raise ValueError("'day' not within supported range")

    if hour is None:
        hour = HOUR_EMPTY
    elif not HOUR_MIN <= hour <= HOUR_MAX:
        raise ValueError("'hour' not within supported range")

    if minute is None:
        minute = MINUTE_EMPTY
    elif not MINUTE_MIN <= minute <= MINUTE_MAX:
        raise ValueError("'minute' not within supported range")

    if second is None:
        second = SECOND_EMPTY
    elif not SECOND_MIN <= second <= SECOND_MAX:
        raise ValueError("'second' not within supported range")

    if (millisecond is not None
            and not MILLISECOND_MIN <= millisecond <= MILLISECOND_MAX):
        raise ValueError("'millisecond' not within supported range")

    if (microsecond is not None
            and not MICROSECOND_MIN <= microsecond <= MICROSECOND_MAX):
        raise ValueError("'microsecond' not within supported range")

    if (nanosecond is not None
            and not NANOSECOND_MIN <= nanosecond <= NANOSECOND_MAX):
        raise ValueError("'nanosecond' not within supported range")

    #
    # Byte packing
    #

    d = year << 9 | month << 5 | day
    t = hour << 12 | minute << 6 | second

    if type == 'D':
        # 100DDDDD DDDDDDDD DDDDDDDD
        return pack_4(0x800000 | d)[-3:]

    elif type == 'T':
        # 1010000T TTTTTTTT TTTTTTTT
        return pack_4(0xa00000 | t)[-3:]

    elif type == 'DT':
        # 00DDDDDD DDDDDDDD DDDDDDDT TTTTTTTT
        # TTTTTTTT
        return pack_8(d << 17 | t)[-5:]

    elif type == 'DTS':
        if nanosecond is not None:
            # 01PPDDDD DDDDDDDD DDDDDDDD DTTTTTTT
            # TTTTTTTT TTSSSSSS SSSSSSSS SSSSSSSS
            # SSSSSSSS
            return pack_2_8(
                0b0110 << 4 | d >> 17,
                (d & 0x1ffff) << 47 | t << 30 | nanosecond)[-9:]
        elif microsecond is not None:
            # 01PPDDDD DDDDDDDD DDDDDDDD DTTTTTTT
            # TTTTTTTT TTSSSSSS SSSSSSSS SSSSSS00
            return pack_8(
                0b0101 << 60 | d << 39 | t << 22 | microsecond << 2)
        elif millisecond is not None:
            # 01PPDDDD DDDDDDDD DDDDDDDD DTTTTTTT
            # TTTTTTTT TTSSSSSS SSSS0000
            return pack_8(
                0b0100 << 52 | d << 31 | t << 14 | millisecond << 4)[-7:]
        else:
            # 01PPDDDD DDDDDDDD DDDDDDDD DTTTTTTT
            # TTTTTTTT TT000000
            return pack_8(0b0111 << 44 | d << 23 | t << 6)[-6:]

    raise NotImplementedError()


def unpackb(value):
    if not 3 <= len(value) <= 10:
        raise ValueError("value must be between 3 and 10 bytes")

    #
    # Unpack components
    #

    first = value[0]
    if PY2:
        first = ord(first)

    d = t = millisecond = microsecond = nanosecond = None

    if first <= 0b00111111:
        # Type DT, tag 00

        if not len(value) == 5:
            raise ValueError(
                "DT value must be 5 bytes; got {0:d}".format(len(value)))

        n = unpack_8(value)
        d = n >> 17 & D_MASK
        t = n & T_MASK

    elif first <= 0b01111111:
        # Type DTS, tag 01

        precision = first >> 4 & 0x03
        expected_length = 6 if precision == 3 else 7 + precision
        if not len(value) == expected_length:
            raise ValueError(
                "DTS value has incorrect length; expected, {0:d}, "
                "got {1:d}".format(expected_length, len(value)))

        # 01PPDDDD DDDDDDDD DDDDDDDD DTTTTTTT
        # TTTTTTTT TT...... (first 6 bytes)
        n = unpack_8(value[:6]) >> 6
        d = n >> 23 & D_MASK
        t = n >> 6 & T_MASK

        # Extract S component from last 4 bytes
        n = unpack_4(value[-4:])
        if precision == 0:
            # 01PPDDDD DDDDDDDD DDDDDDDD DTTTTTTT
            # TTTTTTTT TTSSSSSS SSSS0000
            millisecond = n >> 4 & MILLISECOND_MASK
        elif precision == 1:
            # 01PPDDDD DDDDDDDD DDDDDDDD DTTTTTTT
            # TTTTTTTT TTSSSSSS SSSSSSSS SSSSSS00
            microsecond = n >> 2 & MICROSECOND_MASK
        elif precision == 2:
            # 01PPDDDD DDDDDDDD DDDDDDDD DTTTTTTT
            # TTTTTTTT TTSSSSSS SSSSSSSS SSSSSSSS
            # SSSSSSSS
            nanosecond = n & NANOSECOND_MASK
        elif precision == 3:
            # 01PPDDDD DDDDDDDD DDDDDDDD DTTTTTTT
            # TTTTTTTT TT000000
            pass

    elif first <= 0b10011111:
        # Type D, tag 100

        if not len(value) == 3:
            raise ValueError(
                "D value must be 3 bytes; got {0:d}".format(len(value)))

        d = unpack_4(value) & D_MASK

    elif first <= 0b10100001:
        # Type T, tag 1010000

        if not len(value) == 3:
            raise ValueError(
                "T value must be 3 bytes; got {0:d}".format(len(value)))

        t = unpack_4(value) & T_MASK

    elif first <= 0b10111111:
        raise ValueError("first byte does not contain a valid tag")

    elif first <= 0b11011111:  # tag 110
        raise NotImplementedError("DTZ")

    elif first <= 0b11111111:  # tag 111
        raise NotImplementedError("DTSZ")

    #
    # Split D and T components
    #

    if d is None:
        year = month = day = None
    else:
        year = d >> 9 & YEAR_MASK
        month = (d >> 5 & MONTH_MASK) + 1
        day = (d & DAY_MASK) + 1

    if t is None:
        hour = minute = second = None
    else:
        hour = t >> 12 & HOUR_MASK
        minute = t >> 6 & MINUTE_MASK
        second = t & SECOND_MASK

    #
    # Sub-second fields are either all None, or none are None.
    #

    if millisecond is not None:
        microsecond = millisecond * 1000
        nanosecond = microsecond * 1000
    elif microsecond is not None:
        millisecond = microsecond // 1000
        nanosecond = microsecond * 1000
    elif nanosecond is not None:
        microsecond = nanosecond // 1000
        millisecond = microsecond // 1000

    return Value(
        year, month, day,
        hour, minute, second,
        millisecond, microsecond, nanosecond,
        None, None, None,  # TODO: timezone
    )
