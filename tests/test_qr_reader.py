import json
import sys
from pathlib import Path
import qrcode
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qr_pay import crc16
root=Path(__file__).resolve().parent
fields=[('00','01'),('01','11'),('26','0004TEST'),('52','5999'),('53','050'),('58','BD'),('59','DigitXBD'),('60','DHAKA')]
base=''.join(k+f'{len(v):02d}'+v for k,v in fields)+'6304'
payload=base+crc16(base)
image=qrcode.make(payload).get_image().convert('RGBA')
image.save(root/'merchant-qr-test.png')
(root/'qr-pixels.json').write_text(json.dumps(dict(width=image.width,height=image.height,data=list(image.tobytes()),expected=payload)))
print('QR image fixture prepared.')
