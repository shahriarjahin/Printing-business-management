"""EMV merchant QR parsing, CRC validation, and amount insertion.

Only merchant-provided payloads are accepted. Acquirer approval is still required:
an EMV-valid payload alone cannot guarantee acceptance by a banking app.
"""
from decimal import Decimal


def crc16(text):
    crc = 0xFFFF
    for byte in text.encode('utf-8'):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return f'{crc:04X}'


def parse(payload):
    if not isinstance(payload, str) or not payload or len(payload.encode()) > 2900:
        raise ValueError('Paste the decoded merchant EMV QR payload (maximum 2,900 bytes).')
    data = payload.encode('utf-8')
    pos, fields = 0, []
    while pos < len(data):
        header = data[pos:pos + 4]
        if len(header) != 4 or not header.isdigit():
            raise ValueError('Invalid EMV tag or length.')
        tag = header[:2].decode()
        length = int(header[2:])
        value = data[pos + 4:pos + 4 + length]
        if len(value) != length or tag in dict(fields):
            raise ValueError('Truncated or duplicate EMV field.')
        fields.append((tag, value.decode('utf-8')))
        pos += length + 4
    values = dict(fields)
    if fields[-1][0] != '63' or values.get('63', '').upper() != crc16(payload[:-4]):
        raise ValueError('Merchant QR checksum does not match.')
    if values.get('00') != '01' or values.get('53') != '050' or values.get('58') != 'BD':
        raise ValueError('Use a Bangladesh merchant QR with BDT currency (050) and country BD.')
    if not any(str(n).zfill(2) in values for n in range(2, 52)):
        raise ValueError('Merchant account information is missing.')
    return fields


def with_amount(payload, amount_cents):
    if not isinstance(amount_cents, int) or amount_cents <= 0:
        raise ValueError('QR payment amount must be positive.')
    fields = parse(payload)
    values = dict(fields)
    values['01'] = '12'  # Transaction-specific merchant-presented QR.
    values['54'] = f'{Decimal(amount_cents) / 100:.2f}'
    tags = sorted(set(values) - {'63'})
    result = ''
    for tag in tags:
        value = values[tag]
        length = len(value.encode('utf-8'))
        if length > 99:
            raise ValueError('EMV field is too long.')
        result += f'{tag}{length:02d}{value}'
    result += '6304'
    return result + crc16(result)
