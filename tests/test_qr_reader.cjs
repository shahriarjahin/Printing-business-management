const fs = require('node:fs');
const jsQR = require('../static/vendor/jsQR.js');
const fixture = JSON.parse(fs.readFileSync(__dirname+'/qr-pixels.json','utf8'));
const found = jsQR(new Uint8ClampedArray(fixture.data),fixture.width,fixture.height);
if(!found || found.data!==fixture.expected)throw Error('Merchant QR image decode failed.');
console.log('Merchant QR image decoded correctly.');
